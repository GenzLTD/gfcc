"""
Nazha RAG 诊断脚本 — 追踪每一步实际路径，区分兜底拦截 vs 真实 DeepSeek 调用

Usage: python test_rag_diag.py
"""
import sys
import io
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "static"))
import bootstrap_paths  # noqa: E402

from config.settings import config  # noqa: E402


DIV = "─" * 68


def main():
    # ── 重放 query() 方法逻辑，打印每个分叉点 ──
    from src.vector_store import VectorStore
    from src.db_manager import DBManager
    from src.ai_client import AIClient
    from src.rag_engine import RAGEngine

    rag = RAGEngine()
    query_text = "How to build a practical knowledge base system?"

    print(DIV)
    print("  诊断模式：逐行追踪 RAGEngine.query() 的每一条执行路径")
    print(DIV)
    print(f"\n  Query:  {query_text}")
    print(f"  Config: provider={config.AI_PROVIDER}, search={config.SEARCH_MODE}")
    print(f"  Chroma: {config.CHROMA_PERSIST_DIR}")
    print(f"  Coll:   {config.CHROMA_COLLECTION}")
    print()

    # ==== 第一步：检索 (对应 rag_engine.py:290) ====
    print("[STEP 1] _search() → 检索阶段")
    print(DIV)

    t0 = time.time()
    hits, retrieval_mode = rag._search(query_text, top_k=5, threshold=0.3)
    search_ms = (time.time() - t0) * 1000

    print(f"  ✅ _search() 完成  (耗时 {search_ms:.0f}ms)")
    print(f"  检索模式:      {retrieval_mode}")
    print(f"  返回 hits 数:  {len(hits)}")

    if hits:
        for i, h in enumerate(hits):
            sim = h.get("similarity", 0) * 100
            src = (h.get("metadata") or {}).get("source_file", "?")
            below = " ⚠️低于阈值" if h.get("_below_threshold") else ""
            print(f"  [{i+1}] sim={sim:.1f}%{below} | {src}")
            print(f"       {h['content'][:120]}...")
    else:
        print("  ❌ 无结果 → 会命中「门1：硬编码兜底」")

    # ==== 第二步：命中判断 (对应 rag_engine.py:296) ====
    print(f"\n[STEP 2] 门1 判断 — `if not hits`")
    print(DIV)

    if not hits:
        print("  ⛔ 命中门1！返回硬编码兜底文字，不调用 DeepSeek")
        print('  → 返回: "知识库中暂未找到与您问题相关的资料..."')
    else:
        print("  ✅ 未命中 — 有检索结果，继续往下走")

    # ==== 第三步：AI 可用性 (对应 rag_engine.py:309) ====
    if hits:
        print(f"\n[STEP 3] 门2 判断 — `AIClient.is_configured()`")
        print(DIV)

        ai_ok, ai_hint = AIClient.is_configured()
        print(f"  AI 配置状态:  {ai_ok}")
        print(f"  提示信息:     {ai_hint if ai_hint else '(无)'}")

        if not ai_ok:
            print("  ⛔ 命中门2！走 _retrieval_only_answer() 检索模式，不调用 LLM")
            print('  → 返回以 "⚠️ AI 生成未启用" 开头的结果列表')
        else:
            print("  ✅ 未命中 — AI 已配置，进入 DeepSeek 调用阶段")

    # ==== 第四步：构建 prompt & 调用 DeepSeek (rag_engine.py:323-333) ====
    if hits and ai_ok:
        print(f"\n[STEP 4] 门3 — 构建 prompt + 调用 DeepSeek API")
        print(DIV)

        messages = [
            {"role": "system", "content": rag._build_rag_prompt(query_text, hits)},
        ]
        sys_prompt = messages[0]["content"]
        print(f"  System prompt 长度: {len(sys_prompt)} 字符")
        print(f"  Context 注入块数:   (通过 _build_rag_prompt 中的 hits 注入)")
        print()
        print(f"  ── 发送给 DeepSeek 的 System Prompt 前 500 字符 ──")
        print(f"  {sys_prompt[:500]}...")
        print()

        # 真正调用 DeepSeek
        print("  🚀 正在调用 DeepSeek API...")
        t0 = time.time()
        try:
            answer, elapsed = rag.ai.chat(messages)
            api_ms = (time.time() - t0) * 1000
            print(f"  ✅ DeepSeek API 调用成功 (耗时 {api_ms:.0f}ms)")
            print()
            print(f"  ╔══════════════════════════════════════════════════════════════╗")
            print(f"  ║  DeepSeek 真实回答（非兜底，非模板）                        ║")
            print(f"  ╠══════════════════════════════════════════════════════════════╣")
            for line in answer.split("\n"):
                print(f"  ║  {line}")
            print(f"  ╚══════════════════════════════════════════════════════════════╝")
        except Exception as e:
            print(f"  ❌ DeepSeek API 调用失败: {e}")

    # ==== 总结 ====
    print(f"\n[DONE] 执行路径总结")
    print(DIV)
    if not hits:
        print("  ⛔ 门1拦截 — 检索无结果，未调用 DeepSeek")
    elif not ai_ok:
        print("  ⛔ 门2拦截 — AI 未配置，走检索模式，未调用 DeepSeek")
    else:
        print("  ✅ 完整路径 — 检索→注入上下文→DeepSeek API→返回真实生成结果")


if __name__ == "__main__":
    main()
