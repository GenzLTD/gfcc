"""
Nazha RAG 多问题效果验证脚本 v2
测试三类问题：
  1. D 盘文件索引检索（代码/项目相关）
  2. Cursor 对话记录检索（AI 对话历史）
  3. 综合语义检索
"""
import sys
import io
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "static"))

import bootstrap_paths  # noqa: E402

from src.vector_store import VectorStore
from src.rag_engine import RAGEngine

# ─── 测试问题集 ──────────────────────────────────────
QUERIES = [
    {
        "id": "Q1",
        "category": "Cursor 对话检索",
        "question": "我和 AI 讨论过哪些关于知识库的话题？",
    },
    {
        "id": "Q2",
        "category": "Cursor 对话检索",
        "question": "我之前做过哪些项目的前端开发工作？",
    },
    {
        "id": "Q3",
        "category": "D盘文件索引",
        "question": "DemoPeter 项目的 RAG 引擎是如何实现向量检索的？",
    },
    {
        "id": "Q4",
        "category": "D盘文件索引",
        "question": "Chroma 向量数据库的配置和集合设置在哪里？",
    },
    {
        "id": "Q5",
        "category": "综合检索",
        "question": "Supabase 项目有哪些表结构？",
    },
]

SEP = "=" * 64

def run_rag_query(engine: RAGEngine, question: str):
    """运行一次 RAG 查询，返回 RAGResult 对象"""
    t0 = time.time()
    result = engine.query(question)
    return result


def extract_meta(source: dict) -> str:
    """从 source 里提取可读的来源信息"""
    src = source.get("source", "") or ""
    content = (source.get("content") or "")[:80]
    sim = source.get("similarity", 0)
    retrieval = source.get("retrieval", "?")
    return f"sim={sim:.3f} [{retrieval}] src={src[-50:] if len(src)>50 else src!r} | {content!r}"


def is_cursor_source(source: dict) -> bool:
    """判断 source 是否来自 cursor_conversations"""
    src = source.get("source", "") or ""
    # cursor 对话的 source 可能是空的或包含 session 信息
    # 通过内容特征判断：包含对话文本而非乱码
    content = source.get("content", "") or ""
    # 如果内容里有中文或英文自然语言，且没有 base64 特征
    has_natural_lang = any(ord(c) > 0x4e00 for c in content[:200]) or \
                       any(w in content.lower() for w in ["function", "class", "import", "def ", "const ", "project", "cursor"])
    is_base64_like = len(content) > 100 and '/' in content[:50] and '+' in content[:50]
    return has_natural_lang and not is_base64_like


def main():
    print("Nazha RAG 多问题验证 v2")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    print("\n初始化向量库和 RAG 引擎…")
    vs = VectorStore()
    stats = vs.get_collection_stats()
    print(f"集合: {stats.get('collection_name')}  总向量: {stats.get('total_vectors')}")

    engine = RAGEngine()

    summary = []

    for q in QUERIES:
        print(f"\n{SEP}")
        print(f"[{q['id']}] {q['category']}")
        print(f"问题: {q['question']}")
        print("─" * 40)

        t0 = time.time()
        result = run_rag_query(engine, q["question"])
        elapsed = int((time.time() - t0) * 1000)

        # RAGResult 对象用属性访问
        sources = result.sources or []
        chunk_count = result.chunk_count
        retrieval_mode = result.retrieval_mode
        answer = result.answer or "(无回答)"

        print(f"检索模式: {retrieval_mode}  |  命中: {chunk_count}  |  耗时: {elapsed}ms")

        # 显示 top-3 命中
        readable_cnt = 0
        cursor_cnt = 0
        if sources:
            print(f"\n命中来源 (top {min(3, len(sources))}):")
            for i, src in enumerate(sources[:3]):
                content = (src.get("content") or "")
                sim = src.get("similarity", 0)
                retrieval = src.get("retrieval", "?")
                source_path = src.get("source", "") or ""
                # 检查内容是否可读（非 base64/乱码）
                is_readable = len([c for c in content[:100] if 32 <= ord(c) < 127 or ord(c) > 0x4e00]) > 50
                is_cursor = is_cursor_source(src)
                if is_readable:
                    readable_cnt += 1
                if is_cursor:
                    cursor_cnt += 1
                readable_mark = "📄" if is_readable else "🗑️"
                cursor_mark = " [Cursor对话]" if is_cursor else ""
                print(f"  [{i+1}] {readable_mark} sim={sim:.3f} [{retrieval}]{cursor_mark}")
                if source_path:
                    print(f"       path: {source_path[-60:] if len(source_path)>60 else source_path}")
                print(f"       text: {content[:100].replace(chr(10), ' ')!r}")
        else:
            print("  ⚠ 无命中")

        print(f"\nDeepSeek 回答:")
        if len(answer) > 400:
            print(answer[:400] + "\n…(已截断)")
        else:
            print(answer)

        summary.append({
            "id": q["id"],
            "category": q["category"],
            "hit_count": chunk_count,
            "readable_cnt": readable_cnt,
            "cursor_cnt": cursor_cnt,
            "elapsed_ms": elapsed,
        })

    # 汇总
    print(f"\n\n{'=' * 64}")
    print("验证汇总")
    print(f"{'─' * 60}")
    print(f"{'问题':<6} {'类别':<16} {'命中':<6} {'可读':<6} {'Cursor':<8} {'耗时'}")
    for s in summary:
        print(f"{s['id']:<6} {s['category']:<16} {s['hit_count']:<6} {s['readable_cnt']:<6} {s['cursor_cnt']:<8} {s['elapsed_ms']}ms")

    total_cursor = sum(s["cursor_cnt"] for s in summary)
    total_readable = sum(s["readable_cnt"] for s in summary)
    print(f"\n可读命中: {total_readable}  |  Cursor 对话命中: {total_cursor}")
    print(f"平均耗时: {sum(s['elapsed_ms'] for s in summary)//len(summary)}ms")

    # 额外：直接在向量库层面查一条 cursor 特征数据
    print(f"\n{'─'*60}")
    print("直接向量检索验证（绕过 RAG 引擎，看原始命中）：")
    results = vs.search("知识库 RAG 向量搜索 cursor AI", n_results=5)
    for i, r in enumerate(results[:3]):
        content = (r.get("content") or "")[:120]
        sim = r.get("similarity", 0)
        source = r.get("source", "") or ""
        print(f"  [{i+1}] sim={sim:.3f}  path={source[-50:] if source else '(无)'}  text={content[:80]!r}")


if __name__ == "__main__":
    main()
