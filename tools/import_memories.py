#!/usr/bin/env python3
"""gfcc 记忆体导入器 — 将 jsonl 格式记忆批量写入 agentmemory（经 am-gateway）。

与 04_import_batch.py 同源，但走「网关 :3210 → 桥 :3220 → 引擎」生产链路
（不直连黑盒引擎），自动带 HMAC 令牌（如配置）。

用法：
    python tools/import_memories.py data/chunks.jsonl
    python tools/import_memories.py data/chunks.jsonl --gateway http://localhost:3210 \\
        --token <JWT> --workers 8 --batch 10 --resume

输入格式（jsonl，每行一个 JSON）：
    {"content": "...", "type": "fact", "importance": 5, "metadata": {...}}
    （type 可选 fact/conversation/code/note，importance 1-10，metadata 可选）

断点续传：失败或中断后重跑加 --resume，进度存于 <输入文件>.progress。
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

DEFAULT_GATEWAY = os.environ.get("AM_GATEWAY_URL", "http://127.0.0.1:3210")
REMEMBER_PATH = "/agentmemory/remember"
PROGRESS_SUFFIX = ".progress"


def read_input(path: str):
    """读取 jsonl，返回 list[dict]。兼容缺字段补默认值。"""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARN {path}:{lineno} 跳过非法行: {e}")
                continue
            rows.append(
                {
                    "content": obj.get("content", ""),
                    "type": obj.get("type", "fact"),
                    "importance": int(obj.get("importance", 5)),
                    "metadata": obj.get("metadata"),
                }
            )
    return rows


def load_progress(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def save_progress(path: str, count: int):
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(count))


def remember(client: httpx.Client, gateway: str, headers: dict, row: dict, timeout: float) -> None:
    payload = {"content": row["content"], "type": row["type"], "importance": row["importance"]}
    if row.get("metadata"):
        payload["metadata"] = row["metadata"]
    resp = client.post(f"{gateway}{REMEMBER_PATH}", json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="jsonl 记忆文件路径")
    p.add_argument("--gateway", default=DEFAULT_GATEWAY, help=f"am-gateway 地址（默认 {DEFAULT_GATEWAY}）")
    p.add_argument("--token", default=os.environ.get("AM_TOKEN", ""), help="Bearer 令牌（HMAC 严格模式必需）")
    p.add_argument("--workers", type=int, default=8, help="并发数（默认 8）")
    p.add_argument("--batch", type=int, default=10, help="每批打印进度的条数（默认 10）")
    p.add_argument("--timeout", type=float, default=30.0, help="单条超时秒数（默认 30）")
    p.add_argument("--resume", action="store_true", help="从上次进度续传")
    p.add_argument("--batch-limit", type=int, default=0, help="最多导入条数，0=全部（调试用）")
    args = p.parse_args()

    rows = read_input(args.input)
    if not rows:
        print("空输入，退出")
        return 1
    if args.batch_limit > 0:
        rows = rows[: args.batch_limit]

    progress_file = args.input + PROGRESS_SUFFIX
    start = load_progress(progress_file) if args.resume else 0
    if start > 0:
        print(f"续传：跳过前 {start} 条")
    pending = rows[start:]

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    ok = fail = 0
    t0 = time.time()
    with httpx.Client(headers=headers) as client, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(remember, client, args.gateway, headers, row, args.timeout): i
                for i, row in enumerate(pending, start + 1)}
        done = 0
        for fut in as_completed(futs):
            idx = futs[fut]
            done += 1
            try:
                fut.result()
                ok += 1
            except httpx.HTTPStatusError as e:
                fail += 1
                print(f"FAIL 第{idx}条 {e.response.status_code}: {e.response.text[:120]}")
            except Exception as e:
                fail += 1
                print(f"FAIL 第{idx}条: {e}")
            if done % args.batch == 0 or done == len(futs):
                save_progress(progress_file, idx)
                el = time.time() - t0
                print(f"进度 {done}/{len(futs)}  成功{ok} 失败{fail}  耗时{el:.0f}s")

    save_progress(progress_file, start + len(pending))
    print(f"完成：成功 {ok}，失败 {fail}，耗时 {time.time() - t0:.0f}s")
    if fail:
        print(f"提示：重跑加 --resume 可跳过已成功部分（进度文件 {progress_file}）")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
