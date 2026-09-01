"""
szpeter2026 - Web 管理面板
吸收自 Wukong web_dashboard.py，提供知识库管理、RAG 问答、统计报表
"""
import sys
import json
from pathlib import Path

# 添加项目根目录到路径（static/src → 上三级为项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import bootstrap_paths  # noqa: F401,E402

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename

from config.settings import config
from config.logging_config import setup_logging, get_logger

# 初始化日志系统
logger = setup_logging(
    log_dir=config.PROJECT_ROOT / "logs",
    level="DEBUG" if config.WEB_DEBUG else "INFO",
)

from src.db_manager import DBManager
from src.doc_processor import DocumentProcessor
from src.vector_store import VectorStore
from src.pgvector_store import PgvectorStore
from src.rag_engine import RAGEngine
from src.ai_client import AIClient
from src.report_gen import ReportGenerator
from src.gitea_webhook import GiteaWebhookHandler
from src.outlook_client import OutlookClient
from src.ethos_bootstrap import init_ethos_guard

# D 盘自动索引
from d_indexer import DScanner, DIndexer, DScheduler, ScanConfig, ScanCheckpoint
from d_indexer.projects import D_PROJECT_ROOTS

app = Flask(__name__, template_folder=str(config.TEMPLATES_DIR),
            static_folder=str(config.STATIC_DIR))
CORS(app)
# ethos 统一安全接入（认证/鉴权/审计；无 ETHOS_AUTH_SECRET → 本地 Stub 放行）
init_ethos_guard(app)

db = DBManager()
processor = DocumentProcessor()
vector_store = VectorStore()
pgvector_store = PgvectorStore()
rag = RAGEngine()
reporter = ReportGenerator()
webhook_handler = GiteaWebhookHandler()

# D 盘索引初始化
d_scanner = DScanner(ScanConfig(project_roots=D_PROJECT_ROOTS))
d_checkpoint = ScanCheckpoint()
d_indexer = DIndexer(scanner=d_scanner,
                      persist_dir=str(config.PROJECT_ROOT / "db" / "d_index_data"),
                      checkpoint=d_checkpoint)
d_scheduler = DScheduler(d_indexer, scan_hour=3, scan_minute=0)


# ===== 页面路由 =====

@app.route("/")
def index():
    """主页 — 知识库仪表盘"""
    stats = db.get_stats()
    vec_stats = vector_store.get_collection_stats()
    pg_stats = pgvector_store.get_stats() if pgvector_store.is_available else {"available": False}
    return render_template("index.html", stats=stats, vec_stats=vec_stats,
                           pg_stats=pg_stats, ai_provider=config.AI_PROVIDER)


@app.route("/documents")
def documents_page():
    """文档管理页面"""
    return render_template("documents.html")


@app.route("/query")
def query_page():
    """RAG 问答页面"""
    ai_ok, ai_hint = AIClient.is_configured()
    return render_template(
        "query.html",
        ai_provider=config.AI_PROVIDER,
        ai_configured=ai_ok,
        ai_hint=ai_hint,
    )


@app.route("/reports")
def reports_page():
    """报告页面"""
    return render_template("reports.html")


@app.route("/d-search")
def d_search_page():
    """D 盘文件语义搜索页面"""
    stats = d_indexer.list_projects() if d_indexer.is_available else []
    return render_template("d_search.html",
                           projects=stats,
                           index_available=d_indexer.is_available,
                           chunk_count=d_indexer.count)


# ===== API — 统计 =====

@app.route("/api/stats")
def api_stats():
    """获取知识库统计"""
    stats = db.get_stats()
    stats["chroma"] = vector_store.get_collection_stats()
    stats["pgvector"] = pgvector_store.get_stats() if pgvector_store.is_available else {"available": False}
    stats["ai_provider"] = config.AI_PROVIDER
    return jsonify(stats)


# ===== API — 文档管理 =====

@app.route("/api/documents")
def api_documents():
    """获取文档列表"""
    status = request.args.get("status")
    docs = db.get_documents(status=status)
    return jsonify(docs)


@app.route("/api/documents/<int:doc_id>")
def api_document(doc_id):
    """获取单个文档详情"""
    doc = db.get_document(doc_id)
    if not doc:
        return jsonify({"error": "文档不存在"}), 404
    chunks = db.get_chunks(doc_id)
    doc["chunks"] = chunks
    return jsonify(doc)


@app.route("/api/health/vector")
def api_vector_health():
    """向量存储健康检查 API"""
    health = vector_store.health_check()
    pg_available = pgvector_store.is_available
    return jsonify({
        "chroma": health,
        "pgvector": {"available": pg_available},
        "search_mode": config.SEARCH_MODE,
        "fallback_chain": [
            "Chroma 向量检索",
            "pgvector 向量检索 (备选)",
            "SQLite FTS5 关键词检索 (兜底)",
        ],
    })


@app.route("/api/health/config")
def api_config_health():
    """配置健康检查 — 验证路径和依赖"""
    result = config.health_check()
    result["ollama_models_dir"] = config.OLLAMA_MODELS_DIR
    result["actual_ollama_data"] = _find_ollama_data()
    return jsonify(result)


def _find_ollama_data() -> dict:
    """实地勘查 Ollama 数据位置"""
    candidates = [
        str(config.OLLAMA_MODELS_DIR),
        "D:/ollama-models",
        str(Path.home() / ".ollama" / "models"),
        "D:/DevTools/.ollama/models",
    ]
    found = {}
    for c in candidates:
        try:
            p = Path(c)
            if p.exists():
                blob_count = len(list(p.rglob("*"))) if p.is_dir() else 0
                found[c] = {"exists": True, "files": blob_count}
            else:
                found[c] = {"exists": False}
        except OSError:
            found[c] = {"exists": False, "error": "path inaccessible"}
    return found


@app.route("/api/health/chroma")
def api_chroma_deep_health():
    """Chroma 深度健康检查 — SQLite + Segment 双向验证"""
    import sqlite3
    chroma_dir = Path(config.CHROMA_PERSIST_DIR)
    result = {
        "path": str(chroma_dir),
        "exists": chroma_dir.exists(),
        "collections": [],
        "discrepancies": [],
    }

    if not chroma_dir.exists():
        result["error"] = "Chroma 目录不存在"
        return jsonify(result)

    # 1. SQLite 分析
    sqlite_path = chroma_dir / "chroma.sqlite3"
    if sqlite_path.exists():
        try:
            conn = sqlite3.connect(str(sqlite_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM collections")
            collections = [r[0] for r in cur.fetchall()]

            for col_name in collections:
                try:
                    cur.execute(
                        "SELECT COUNT(*) FROM embeddings "
                        "WHERE segment_id IN (SELECT id FROM segments "
                        "WHERE collection IN (SELECT id FROM collections WHERE name=?))",
                        (col_name,),
                    )
                    sql_count = cur.fetchone()[0]
                except Exception:
                    sql_count = -1

                result["collections"].append({
                    "name": col_name,
                    "sqlite_embeddings": sql_count,
                })
            conn.close()
        except Exception as e:
            result["sqlite_error"] = str(e)

    # 2. Segment 文件分析
    segment_dirs = list(chroma_dir.glob("*/"))
    for sd in segment_dirs:
        if sd.is_dir() and sd.name != "__pycache__":
            bin_files = list(sd.glob("data_level*.bin"))
            bin_size = sum(f.stat().st_size for f in bin_files)
            segment_info = {
                "id": sd.name,
                "bin_files": len(bin_files),
                "total_bytes": bin_size,
                "total_mb": round(bin_size / 1024 / 1024, 2),
            }
            # 对比 Chroma API 计数
            try:
                import chromadb
                client = chromadb.PersistentClient(path=str(chroma_dir))
                for col in client.list_collections():
                    api_count = col.count()
                    for entry in result["collections"]:
                        if entry["name"] == col.name:
                            entry["chroma_api_count"] = api_count
                            # 检测异常
                            if api_count == 0 and bin_size > 100_000:
                                result["discrepancies"].append({
                                    "type": "api_zero_but_large_segment",
                                    "collection": col.name,
                                    "details": (
                                        f"Chroma API 报告 0 vectors，但 segment "
                                        f"文件占用 {round(bin_size/1024/1024, 1)}MB"
                                    ),
                                })
            except Exception:
                pass

    # 3. 总健康评分
    total_discrepancies = len(result["discrepancies"])
    result["healthy"] = total_discrepancies == 0
    result["summary"] = (
        "正常" if total_discrepancies == 0
        else f"{total_discrepancies} 个异常"
    )

    return jsonify(result)


@app.route("/api/documents/import", methods=["POST"])
def api_import_documents():
    """批量导入文档"""
    data = request.get_json() or {}
    raw_path = data.get("directory") or ""
    if raw_path:
        # 相对路径 → 基于项目根目录解析为绝对路径
        directory = str(Path(raw_path).resolve()
                        if Path(raw_path).is_absolute()
                        else (config.PROJECT_ROOT / raw_path).resolve())
    else:
        directory = str(config.DOCS_DIR)
    if not Path(directory).exists():
        return jsonify({"error": f"目录不存在: {directory}",
                        "details": [], "total": 0, "success": 0, "failed": 0}), 400

    # 扫描文件
    files = processor.scan_directory(directory)
    results = {"total": len(files), "success": 0, "failed": 0, "details": []}

    for file_info in files:
        try:
            detail = _process_one_file(
                file_path=file_info["file_path"],
                title=file_info["title"],
                doc_type=file_info["doc_type"],
                file_size=file_info.get("file_size", 0),
            )
            if detail.get("status") == "completed":
                results["success"] += 1
            elif detail.get("status") == "skipped":
                results["details"].append(detail)
                continue
            results["details"].append(detail)

        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "title": file_info["title"],
                "status": "failed",
                "reason": str(e)[:200],
            })

    return jsonify(results)


def _process_one_file(file_path: str, title: str, doc_type: str, file_size: int) -> dict:
    """处理单个文件：注册 → 提取 → 分块 → 写入向量库（复用逻辑）"""
    # 检查是否已存在
    existing = db.get_documents()
    existing_paths = {d.get("file_path", "") for d in existing if isinstance(d, dict)}
    if file_path in existing_paths:
        return {"title": title, "status": "skipped", "reason": "已存在"}

    doc_id = db.register_document(
        title=title, file_path=file_path,
        doc_type=doc_type, file_size=file_size,
    )

    text, chunks = processor.process_file(file_path)
    db.save_chunks(doc_id, chunks)

    vector_write_ok = True
    if vector_store.is_available:
        added = vector_store.add_documents(str(doc_id), chunks)
        if added > 0 and chunks:
            verify_hits = vector_store.search(chunks[0]["content"][:100], top_k=1, threshold=0.0)
            if not verify_hits:
                vector_write_ok = False

    if pgvector_store.is_available:
        pgvector_store.add_documents(doc_id, chunks)

    status = "completed" if vector_write_ok else "completed_no_vector"
    db.update_document_status(doc_id, status, len(chunks))
    return {"title": title, "doc_id": doc_id, "status": "completed", "chunks": len(chunks)}


@app.route("/api/documents/upload", methods=["POST"])
def api_upload_documents():
    """上传文件并批量导入 — 从浏览器直接上传文档"""
    if "files" not in request.files:
        return jsonify({"error": "请选择文件", "details": [], "total": 0, "success": 0, "failed": 0}), 400

    files = request.files.getlist("files")
    # 确保上传目录存在
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    results = {"total": len(files), "success": 0, "failed": 0, "details": []}

    for f in files:
        if not f.filename:
            continue
        try:
            safe_name = secure_filename(f.filename)
            save_path = config.UPLOAD_DIR / safe_name
            f.save(str(save_path))

            resolved = str(save_path.resolve())
            suffix = save_path.suffix.lower().lstrip(".")
            file_size = save_path.stat().st_size

            detail = _process_one_file(
                file_path=resolved,
                title=save_path.stem,
                doc_type=suffix,
                file_size=file_size,
            )
            if detail.get("status") == "completed":
                results["success"] += 1
            elif detail.get("status") == "skipped":
                detail["status"] = "skipped"
            results["details"].append(detail)
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "title": f.filename,
                "status": "failed",
                "reason": str(e)[:200],
            })

    return jsonify(results)


@app.route("/api/documents/<int:doc_id>", methods=["DELETE"])
def api_delete_document(doc_id):
    """删除文档"""
    db.delete_document(doc_id)
    if vector_store.is_available:
        vector_store.delete_document(str(doc_id))
    if pgvector_store.is_available:
        pgvector_store.delete_document(doc_id)
    return jsonify({"status": "deleted", "doc_id": doc_id})


# ===== API — RAG 问答 =====

@app.route("/api/rag/query", methods=["POST"])
def api_rag_query():
    """RAG 问答"""
    data = request.get_json()
    query_text = (data or {}).get("query", "").strip()
    if not query_text:
        return jsonify({"error": "请输入问题"}), 400

    top_k = data.get("top_k", 5)
    threshold = data.get("threshold", 0.7)

    try:
        result = rag.query(query_text, top_k=top_k, threshold=threshold)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"问答失败: {exc}"}), 500

    ai_ok, _ = AIClient.is_configured()
    return jsonify({
        "query": result.query,
        "answer": result.answer,
        "sources": result.sources,
        "response_time_ms": result.response_time_ms,
        "chunk_count": result.chunk_count,
        "retrieval_mode": result.retrieval_mode,
        "ai_configured": ai_ok,
        "retrieval_only": "+retrieval_only" in (result.retrieval_mode or ""),
    })


@app.route("/api/rag/stream")
def api_rag_stream():
    """流式 RAG 问答"""
    query_text = request.args.get("query", "").strip()
    if not query_text:
        return jsonify({"error": "请输入问题"}), 400

    top_k = request.args.get("top_k", 5, type=int)
    threshold = request.args.get("threshold", 0.7, type=float)

    def generate():
        try:
            ai_ok, _ = AIClient.is_configured()
            stream_gen, hits = rag.query_stream(
                query_text, top_k=top_k, threshold=threshold,
            )
            retrieval_only = not ai_ok
            if hits and not retrieval_only:
                sources_payload = [{
                    "content": h["content"][:1200],
                    "source": h["metadata"].get("source_file", ""),
                    "similarity": h.get("similarity", 0),
                    "below_threshold": h.get("_below_threshold", False),
                } for h in hits]
                yield f"data: {json.dumps({'type': 'sources', 'data': sources_payload, 'retrieval_only': False}, ensure_ascii=False)}\n\n"
            elif hits and retrieval_only:
                yield f"data: {json.dumps({'type': 'meta', 'retrieval_only': True, 'chunk_count': len(hits)}, ensure_ascii=False)}\n\n"
            for chunk in stream_gen:
                if isinstance(chunk, float):
                    yield f"data: {json.dumps({'type': 'done', 'time_ms': chunk * 1000}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'text', 'content': chunk}, ensure_ascii=False)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'问答失败: {exc}'}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


# ===== API — 报告 =====

@app.route("/api/reports/generate", methods=["POST"])
def api_generate_report():
    """生成报告"""
    data = request.get_json() or {}
    report_type = data.get("type", "daily")
    if report_type == "daily":
        path = reporter.generate_daily()
    elif report_type == "weekly":
        path = reporter.generate_weekly()
    elif report_type == "monthly":
        path = reporter.generate_monthly()
    else:
        return jsonify({"error": f"不支持的报告类型: {report_type}"}), 400
    return jsonify({"status": "generated", "path": path, "type": report_type})


@app.route("/api/reports/queries")
def api_recent_queries():
    """最近查询记录"""
    limit = request.args.get("limit", 20, type=int)
    queries = db.get_recent_queries(limit=limit)
    return jsonify(queries)


# ===== API — 系统 =====

@app.route("/api/system/check")
def api_system_check():
    """系统健康检查"""
    vec_stats = vector_store.get_collection_stats()
    pg_stats = pgvector_store.get_stats() if pgvector_store.is_available else {"available": False}
    ai_ok, ai_hint = AIClient.is_configured()
    return jsonify({
        "status": "ok",
        "ai_provider": config.AI_PROVIDER,
        "ai_configured": ai_ok,
        "ai_hint": ai_hint if not ai_ok else "",
        "chroma": {
            "available": vec_stats.get("available"),
            "mode": vec_stats.get("mode"),
            "vectors": vec_stats.get("total_vectors", 0),
        },
        "pgvector": pg_stats,
        "db_path": config.METADATA_DB,
    })


# ===== Outlook OAuth 回调 =====

@app.route("/auth/outlook/callback")
def auth_outlook_callback():
    """Microsoft OAuth2 回调 — 用授权码换取 token"""
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return f"<h2>授权失败</h2><p>{error}</p>", 400
    if not code:
        return "<h2>缺少授权码</h2>", 400
    try:
        client = OutlookClient()
        client.exchange_code(code)
        return "<h2>✅ 授权成功！</h2><p>Outlook 邮箱已连接，可以关闭此页面。</p>"
    except Exception as e:
        return f"<h2>❌ 授权失败</h2><p>{e}</p>", 500


@app.route("/auth/outlook/login")
def auth_outlook_login():
    """跳转到 Microsoft 授权页面"""
    auth_url = OutlookClient.get_auth_url()
    return f'<meta http-equiv="refresh" content="0;url={auth_url}"><p>正在跳转到 Microsoft 登录...</p>'


# ===== Gitea Webhook =====

@app.route("/api/webhook/gitea", methods=["POST"])
def api_gitea_webhook():
    """接收 Gitea webhook 事件并同步到 Notion"""
    # 验证签名
    if not webhook_handler.verify_signature(request):
        return jsonify({"status": "error", "message": "签名验证失败"}), 403

    # 处理事件
    result = webhook_handler.handle(request)
    return jsonify(result)


# ===== API — D 盘索引 =====

@app.route("/api/d-index/search")
def api_d_index_search():
    """语义搜索 D 盘文件"""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "请输入搜索词"}), 400

    top_k = request.args.get("top_k", 10, type=int)
    project = request.args.get("project")
    file_type = request.args.get("type")

    results = d_indexer.search(q, top_k=top_k, project_filter=project, file_type_filter=file_type)
    return jsonify({
        "query": q,
        "results": [
            {
                "file_path": r.file_path,
                "source_paths": r.source_paths,
                "source_count": r.source_count,
                "project": r.project_name,
                "content": r.content,
                "file_type": r.file_type,
                "similarity": r.similarity,
                "last_modified": r.last_modified,
            }
            for r in results
        ],
        "total": len(results),
    })


@app.route("/api/d-index/scan", methods=["POST"])
def api_d_index_scan():
    """手动触发 D 盘扫描

    mode 可选值:
      - incremental: 增量扫描（默认，仅索引变更文件）
      - full: 全量扫描（重置所有断点，从头开始）
      - resume: 断点续传（从中断处继续未完成的扫描）
    """
    data = request.get_json() or {}
    mode = data.get("mode", "incremental")

    if mode == "full":
        d_indexer.checkpoint.reset_all()
        result = d_indexer.index_with_resume(resume=True)
    elif mode == "resume":
        result = d_indexer.index_with_resume(resume=True)
    elif mode == "incremental":
        result = d_indexer.incremental_scan()
    else:
        return jsonify({"error": f"未知模式: {mode}"}), 400

    return jsonify({
        "mode": mode,
        "total_files": result.total_files,
        "new_chunks": result.new_chunks,
        "skipped_chunks": result.skipped_chunks,
        "skipped_files": result.skipped_files,
        "duration_seconds": result.scan_duration_seconds,
        "timestamp": result.last_scan_time,
    })


@app.route("/api/d-index/stats")
def api_d_index_stats():
    """D 盘索引导航"""
    if not d_indexer.is_available:
        return jsonify({"available": False, "chunks": 0, "projects": []})

    projects = d_indexer.list_projects()
    return jsonify({
        "available": True,
        "chunks": d_indexer.count,
        "projects": projects,
        "collection": "d_drive_index",
        "project_roots": len(D_PROJECT_ROOTS),
        "scheduler_running": d_scheduler.is_running,
        "last_scan": d_scheduler.last_scan_time,
    })


@app.route("/api/d-index/checkpoint")
def api_d_index_checkpoint():
    """获取所有项目的断点/扫描进度"""
    progress_list = d_scheduler.get_checkpoint_status()
    cache_stats = d_indexer.checkpoint.get_cache_stats()

    return jsonify({
        "projects": [
            {
                "project_root": p.project_root,
                "status": p.status,
                "completed_dirs_count": len(p.completed_dirs),
                "current_dir": p.current_dir,
                "current_file": p.current_file,
                "files_scanned": p.files_scanned,
                "files_indexed": p.files_indexed,
                "chunks_indexed": p.chunks_indexed,
                "started_at": p.started_at,
                "updated_at": p.updated_at,
            }
            for p in progress_list
        ],
        "has_incomplete": d_indexer.checkpoint.has_incomplete(),
        "cache": cache_stats,
    })


@app.route("/api/d-index/checkpoint/reset", methods=["POST"])
def api_d_index_checkpoint_reset():
    """重置断点（可选指定项目）"""
    data = request.get_json() or {}
    project = data.get("project_root")

    if project:
        d_indexer.checkpoint.reset_project(project)
        return jsonify({"reset": project})
    else:
        d_indexer.checkpoint.reset_all()
        return jsonify({"reset": "all"})


@app.route("/api/d-index/checkpoint", methods=["DELETE"])
def api_d_index_checkpoint_delete():
    """删除某个项目的文件缓存"""
    data = request.get_json() or {}
    project = data.get("project_root")

    if project:
        d_indexer.checkpoint.delete_project_cache(project)
        return jsonify({"deleted_cache": project})
    else:
        return jsonify({"error": "需要指定 project_root"}), 400


@app.route("/api/d-index/projects")
def api_d_index_projects():
    """已索引项目列表"""
    projects = d_indexer.list_projects() if d_indexer.is_available else []
    scheduled = d_scheduler.is_running
    return jsonify({
        "projects": projects,
        "scheduler_running": scheduled,
        "last_scan": d_scheduler.last_scan_time,
    })


@app.route("/api/d-index/clear", methods=["POST"])
def api_d_index_clear():
    """清空 D 盘索引"""
    if not d_indexer.is_available:
        return jsonify({"error": "索引不可用"}), 500
    d_indexer.clear_index()
    return jsonify({"status": "cleared"})


# ===== 启动入口 =====

def main():
    vec_stats = vector_store.get_collection_stats()
    pg_stats = pgvector_store.get_stats() if pgvector_store.is_available else {"available": False}
    vec_health = vector_store.health_check()

    chroma_status = "不可用"
    if vec_stats.get("available"):
        mode = vec_stats.get("mode", "?")
        count = vec_stats.get("total_vectors", 0)
        emb_status = ""
        emb_ok = vec_health.get("embedding_ok")
        if emb_ok is False:
            emb_status = " [Embedding异常!]"
        elif emb_ok is None:
            emb_status = ""
        else:
            emb_status = " [Embedding正常]"
        chroma_status = f"{mode}模式 ({count} 向量){emb_status}"

    pg_status = "不可用"
    if pg_stats.get("available"):
        v = pg_stats.get("total_vectors", 0)
        m = pg_stats.get("embedding_model", "")
        pg_status = f"pgvector ({v} 向量, {m})"

    ai_ok, ai_hint = AIClient.is_configured()
    ai_status = config.AI_PROVIDER if ai_ok else "未就绪(仅检索模式)"

    # D 盘索引状态
    d_chunks = d_indexer.count if d_indexer.is_available else 0
    d_status = f"已就绪 ({d_chunks} chunks)" if d_indexer.is_available else "不可用"

    # 启动 D 盘每日扫描 [已禁用] - 改为手动触发
    # 如需恢复自动扫描，取消下面的注释：
    # if d_indexer.is_available and not d_scheduler.is_running:
    #     d_scheduler.start()
    #     logger.info("D 盘每日扫描已启动: %02d:%02d", d_scheduler.scan_hour, d_scheduler.scan_minute)
    logger.info("D 盘扫描已禁用自动模式，请使用 POST /api/d-index/scan 手动触发")

    # Embedding 健康警告
    if vec_health.get("embedding_ok") is False:
        logger.warning("Embedding 函数异常，请运行 scripts/verify_persistence.py 排查")
        logger.warning("常见原因: 缺少 onnxruntime → pip install onnxruntime>=1.18.0")

    # 启动健康检查
    health = config.health_check()
    if health["warnings"]:
        for w in health["warnings"]:
            logger.warning("健康检查: %s", w)
    if health["errors"]:
        for e in health["errors"]:
            logger.error("健康检查: %s", e)

    logger.info(
        "DemoPeter 启动: AI=%s Chroma=%s D盘索引=%s 端口=%s",
        ai_status, chroma_status, d_status, config.WEB_PORT,
    )
    print(f"""
╔══════════════════════════════════════════════╗
║       szpeter2026 知识库管理面板            ║
║  AI 提供商: {ai_status:<31}║
║  Chroma:    {chroma_status:<31}║
║  pgvector:  {pg_status:<31}║
║  D盘索引:   {d_status:<31}║
║  Ollama:    {config.OLLAMA_BASE_URL:<31}║
║  Webhook:   /api/webhook/gitea                ║
║  Notion:    {'已配置' if config.NOTION_TOKEN else '未配置':<31}║
║  Health:    http://{config.WEB_HOST}:{config.WEB_PORT}/api/health/config║
║  D盘搜索:   http://{config.WEB_HOST}:{config.WEB_PORT}/d-search║
║  访问地址:  http://{config.WEB_HOST}:{config.WEB_PORT:<21}║
╚══════════════════════════════════════════════╝
    """)
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=config.WEB_DEBUG)


if __name__ == "__main__":
    main()
