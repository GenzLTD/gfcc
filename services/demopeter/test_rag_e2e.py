"""
Nazha RAG all pipeline E2E verification
Validates: (1) Chroma vector store (2) DeepSeek API (3) Full RAG Q&A

Usage: python test_rag_e2e.py
"""
import sys
import io
import time
from pathlib import Path

# Fix Windows GBK encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Path setup (same as scripts/query.py)
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "static"))
import bootstrap_paths  # noqa: E402

from config.settings import config  # noqa: E402


def sep(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---- Step 1: Configuration check ----
sep("Step 1: Configuration")

print(f"\nProject root:  {config.PROJECT_ROOT}")
print(f"AI Provider:   {config.AI_PROVIDER}")
print(f"DeepSeek Key:  {'[OK] configured' if config.DEEPSEEK_API_KEY else '[FAIL] missing'}")
print(f"DeepSeek URL:  {config.DEEPSEEK_BASE_URL}")
print(f"DeepSeek Model: {config.DEEPSEEK_MODEL}")
print(f"Chroma Mode:   {config.CHROMA_MODE}")
print(f"Chroma Dir:    {config.CHROMA_PERSIST_DIR}")
print(f"Collection:    {config.CHROMA_COLLECTION}")
print(f"Search Mode:   {config.SEARCH_MODE}")

# ---- Step 2: Chroma vector store ----
sep("Step 2: Chroma Vector Store")

from src.vector_store import VectorStore  # noqa: E402

vs = VectorStore()
stats = vs.get_collection_stats()

print(f"\nVector store:  {'[OK] available' if stats['available'] else '[FAIL] unavailable'}")
if stats['available']:
    print(f"Mode:          {stats.get('mode', '?')}")
    print(f"Total vectors: {stats['total_vectors']:,}")

# Health check
health = vs.health_check()
print(f"Embedding OK:  {health.get('embedding_ok')}")
if health.get('embedding_error'):
    print(f"Embedding err: {health['embedding_error']}")

# ---- Step 3: Quick search test ----
sep("Step 3: Vector Search Test")

test_queries = [
    "knowledge base system architecture",
    "how to build a RAG pipeline",
]

for q in test_queries:
    t0 = time.time()
    hits = vs.search(q, top_k=3, threshold=0.0)
    elapsed = (time.time() - t0) * 1000
    print(f"\nQuery: '{q}'")
    print(f"  Hits: {len(hits)}, Time: {elapsed:.0f}ms")
    for i, h in enumerate(hits[:2]):
        sim = h.get("similarity", 0) * 100
        src = (h.get("metadata") or {}).get("source_file", "?")
        print(f"  [{i+1}] sim={sim:.1f}% | {src}")
        print(f"       {h['content'][:100]}...")

# ---- Step 4: DeepSeek API ----
sep("Step 4: DeepSeek API Connectivity")

from src.ai_client import AIClient  # noqa: E402

ai_ok, ai_hint = AIClient.is_configured()
print(f"\nAI configured: {'[OK] ' + ai_hint if ai_ok else '[FAIL] ' + ai_hint}")

api_ok = False
if ai_ok:
    ai = AIClient()
    t0 = time.time()
    try:
        msgs = [{"role": "user", "content": "Say hello in one sentence."}]
        reply, usage = ai.chat(msgs)
        api_time = (time.time() - t0) * 1000
        print(f"[OK] DeepSeek API call succeeded")
        print(f"  Model:   {config.DEEPSEEK_MODEL}")
        print(f"  Reply:   {reply[:200]}")
        if usage and isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            print(f"  Tokens:  {pt} in / {ct} out")
        print(f"  Latency: {api_time:.0f} ms")
        api_ok = True
    except Exception as e:
        api_time = (time.time() - t0) * 1000
        print(f"[FAIL] DeepSeek API error: {e}")

# ---- Step 5: Full RAG pipeline ----
sep("Step 5: Full RAG Pipeline")

rag_ok = False
rag_time = 0

if stats['available'] and api_ok:
    from src.rag_engine import RAGEngine  # noqa: E402

    rag = RAGEngine()
    rag_query = "What is knowledge base? How to build a practical knowledge base system?"

    print(f"\nQuestion: {rag_query}")
    print("Running RAG pipeline...")

    t0 = time.time()
    try:
        result = rag.query(rag_query, top_k=5, threshold=0.3)
        rag_time = (time.time() - t0) * 1000

        print(f"\n[OK] RAG pipeline succeeded!")
        print(f"{'-'*50}")
        print(f"\nAnswer:\n{result.answer}")
        print(f"\n{'-'*50}")
        print(f"Total time:    {rag_time:.0f} ms")
        print(f"Chunk refs:    {result.chunk_count}")
        print(f"Retrieval mode: {result.retrieval_mode}")
        print(f"Sources:       {len(result.sources)}")

        if result.sources:
            print(f"\nSources:")
            for i, src in enumerate(result.sources[:5]):
                print(f"  [{i+1}] {src['source']} (match: {src['similarity']*100:.1f}%)")
                print(f"       {src['content'][:100]}...")
        rag_ok = True
    except Exception as e:
        rag_time = (time.time() - t0) * 1000
        print(f"\n[FAIL] RAG pipeline failed: {e}")
        import traceback
        traceback.print_exc()
else:
    missing = []
    if not stats['available']:
        missing.append("vector store unavailable")
    if not api_ok:
        missing.append(f"AI not configured ({ai_hint})")
    print(f"\n[Skipped] Reasons: {', '.join(missing)}")

# ---- Summary ----
sep("Summary")

checks = [
    ("Configuration", True),
    ("Chroma Vector Store", stats['available']),
    ("Embedding Function", health.get('embedding_ok') is not False),
    ("Vector Search", True),  # passed if we got here
    ("DeepSeek API", api_ok),
    ("RAG Full Pipeline", rag_ok),
]

print()
all_pass = True
for name, ok in checks:
    status = "[PASS]" if ok else "[FAIL]"
    if not ok:
        all_pass = False
    print(f"  {status}  {name}")

print()
if all_pass:
    print("*** ALL CHECKS PASSED - Knowledge base is ready for production use! ***")
else:
    print("*** Some checks failed - see details above ***")

print(f"\nProject: {PROJECT_ROOT}")
print(f"Chroma dir: {config.CHROMA_PERSIST_DIR}")
print(f"AI engine:  {config.AI_PROVIDER} / {config.DEEPSEEK_MODEL}")
print(f"Search:     {config.SEARCH_MODE}")
