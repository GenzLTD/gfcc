"""
中央大脑：意图解析 + 分发到内部能力端口。

设计原则：不以占位为长期方案。中央大脑需结合 LLM 进化——意图解析、多轮理解、
编排与反思均可由 LLM 承担，通过改 Prompt 或模型即可迭代；规则仅作无 key 或
LLM 失败时的回退，保证链路可跑通。
"""
import json
import os
import random
import re
from typing import Any

from tatha.core.config import use_llm_intent
from tatha.core.llm import completion as llm_completion
from .schemas import AskRequest, AskResponse

# 支持的意图（与 LLM 的 system prompt 一致，便于进化）
INTENTS = ("job_match", "resume_upload", "poetry", "credit", "mbti", "knowledge", "memory", "unknown")

# 规则回退：关键词 → 意图（仅当 LLM 未启用或失败时使用）
INTENT_KEYWORDS = {
    "poetry": ["诗词", "诗人", "古诗", "推荐一句", "陪伴", "安慰", "思乡", "送别", "山水", "边塞", "励志", "一句诗"],
    "job_match": ["匹配", "职位", "找工作", "有没有适合", "岗位"],
    "resume_upload": ["上传", "简历", "解析简历"],
    "credit": ["征信", "信用", "验证"],
    "mbti": ["人格", "MBTI", "测评", "性格"],
    "knowledge": ["知识库", "帮我查", "查一下", "搜索一下", "资料库", "文档问答", "查资料", "知识问答"],
    "memory": ["记忆", "回忆", "记得", "往事", "之前说过", "历史记录", "agentmemory", "记住", "记下", "记着"],
}

# DemoPeter 知识库服务地址（TATHA_KNOWLEDGE_URL 可覆盖）
KNOWLEDGE_URL = os.getenv("TATHA_KNOWLEDGE_URL", "http://127.0.0.1:5220").rstrip("/")
# agentmemory 记忆网关地址（TATHA_MEMORY_URL 可覆盖；iii-engine 路由黑盒，路径由网关透传）
MEMORY_URL = os.getenv("TATHA_MEMORY_URL", "http://127.0.0.1:3210").rstrip("/")

# 诗词推荐时随机注入主题，避免「推荐一句诗」总返回同一首、结果跑空
POETRY_RECOMMEND_THEMES = ("思乡", "送别", "山水", "边塞", "咏物", "励志", "田园", "怀古")


def _poetry_is_recommendation_query(text: str) -> bool:
    """
    判断是否为「推荐一句诗」类短句（无诗词正文），以便注入随机主题，让推荐结果多样化。
    """
    if not (text and text.strip()) or len(text.strip()) > 80:
        return False
    t = text.strip()
    return bool(re.search(r"推荐|来一句|来首|随便.*诗|一句诗", t))


def _parse_intent_llm(message: str) -> tuple[str, float, dict[str, Any]] | None:
    """
    用 LLM 解析意图（主路径）。返回 (intent, confidence, slots) 或 None（失败时回退）。
    通过改 prompt 或模型即可让中央大脑进化，无需改代码逻辑。
    """
    try:
        system = (
            "你是一个意图分类器。根据用户输入，输出且仅输出一个 JSON 对象，不要其他文字。"
            "JSON 必须包含：\"intent\"（取值仅限: job_match, resume_upload, poetry, credit, mbti, knowledge, memory, unknown），"
            "\"confidence\"（0 到 1 的浮点数），可选 \"slots\"（对象，如 {\"query\": \"...\"}）。"
            "job_match=求职/职位匹配，resume_upload=上传或解析简历，poetry=诗词/诗人/陪伴，credit=征信/验证，mbti=人格测评，knowledge=查询知识库/检索资料，memory=查询/记住/回忆长期记忆或历史记录。"
        )
        resp = llm_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message.strip() or "（无输入）"},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        # 允许被 markdown 代码块包裹
        if "```" in text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if m:
                text = m.group(1).strip()
        data = json.loads(text)
        intent = (data.get("intent") or "unknown").lower()
        if intent not in INTENTS:
            intent = "unknown"
        confidence = float(data.get("confidence", 0.5))
        slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        return (intent, confidence, slots)
    except Exception:
        return None


def _parse_intent_rules(message: str) -> str:
    """规则回退：关键词匹配。"""
    msg = (message or "").strip().lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            return intent
    return "unknown"


def parse_intent(message: str) -> tuple[str, float, dict[str, Any]]:
    """
    解析用户消息得到意图 + 置信度 + 槽位。
    主路径：LLM（可进化）；回退：规则（保证无 key 时也能跑）。
    """
    if use_llm_intent():
        out = _parse_intent_llm(message)
        if out is not None:
            return out
    intent = _parse_intent_rules(message)
    return (intent, 0.8 if intent != "unknown" else 0.3, {})


def _document_analysis(document_type: str, text: str) -> dict[str, Any] | None:
    """
    文档解读：优先 PydanticAI（result_type 数据边界），回退 Marvin（JSON schema 动态）。
    返回可序列化的 dict，无有效结果时返回 None。
    """
    from tatha.core.config import document_analysis_backend
    backend = document_analysis_backend()
    if backend == "pydantic_ai":
        try:
            from tatha.agents import run_document_analysis
            data = run_document_analysis(document_type, text)
            return data.model_dump() if data else None
        except Exception:
            backend = "marvin"
    if backend == "marvin":
        _ensure_extractors_loaded()
        from tatha.ai.fn_from_schema import get_extractor
        extract_fn = get_extractor(document_type)
        if not extract_fn:
            return None
        out = extract_fn(text)
        if out and not out.get("_placeholder"):
            return out
    return None


def _credit_has_document_body(text: str) -> bool:
    """
    判断是否为「信用报告/文档片段」而非短句查询。
    仅当文本像报告内容（含主体/报告类型/摘要等，或足够长）时才返回 True，
    避免把「查一下征信」等短句当正文解析导致结果不稳定。
    """
    if not (text and text.strip()):
        return False
    t = text.strip()
    # 过短且无报告特征：视为查询语
    if len(t) < 25:
        return False
    # 含报告常见字段/用语则视为有正文
    report_markers = ("主体", "报告类型", "摘要", "信用报告", "信用代码", "信用等级", "经营状态", "无不良")
    if any(m in t for m in report_markers):
        return True
    # 较长且含「信用/征信」可能是一段描述
    if len(t) >= 40 and ("信用" in t or "征信" in t):
        return True
    return False


def _ensure_extractors_loaded() -> None:
    """懒加载：若尚未根据 schema 生产函数，则加载默认或配置的 schema 并生产。"""
    from tatha.ai.fn_from_schema import REGISTRY
    if REGISTRY.get("_loaded"):
        return
    from tatha.core.config import get_extractors_schema_path
    path = get_extractors_schema_path()
    if path:
        from tatha.ai.fn_from_schema import load_and_produce
        load_and_produce(path=path)
    REGISTRY["_loaded"] = True


def _call_knowledge_service(
    text: str,
    top_k: int = 5,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """调度 DemoPeter 知识库 RAG（POST /api/rag/query）。

    - HMAC 严格模式：携带 SystemMinter 签发的系统令牌（svc:tatha，tier=admin）；
    - stub 模式：不带头（DemoPeter 侧 Stub 放行，保持本地联调零配置）。
    下游不可达 / 非 2xx / 解析失败 → 抛异常由 dispatch 兜底。
    """
    import httpx

    from .security import security

    headers = {}
    token = security.get_system_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"query": text, "top_k": top_k, "threshold": threshold}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f"{KNOWLEDGE_URL}/api/rag/query", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _call_memory_service(
    text: str,
    limit: int = 10,
) -> dict[str, Any]:
    """检索 agentmemory 记忆（经 ethos 网关 :3210 POST 透传到桥 :3220 调 mem::search）。

    iii-engine :3111 无 /v1/memories/search 路由（必 404），因此走网关写通道：
    POST {MEMORY_URL}/agentmemory/search，body {query, limit}，路径由网关原样透传至桥，
    桥按 ROUTES 无损 JSON 转发为 mem::search。返回 {format, results:[{observation, score}]}。

    - HMAC 严格模式：携带 SystemMinter 签发的系统令牌（svc:tatha，tier=admin）；
    - stub 模式：不带头（网关侧 Stub 放行，保持本地联调零配置）。
    下游不可达 / 非 2xx / 解析失败 → 抛异常由 dispatch 兜底。
    """
    import httpx

    from .security import security

    headers = {}
    token = security.get_system_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"query": text, "limit": limit}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{MEMORY_URL}/agentmemory/search", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _remember_memory_service(
    content: str,
    memory_type: str = "fact",
    importance: int = 5,
) -> dict[str, Any]:
    """写入 agentmemory 记忆（经 ethos 网关 :3210 POST 透传到桥 :3220 调 mem::remember）。

    POST {MEMORY_URL}/agentmemory/remember，body {content, type, importance}，
    返回 {"memory": {...}, "success": true}。

    - HMAC 严格模式：携带 SystemMinter 签发的系统令牌（svc:tatha，tier=admin）；
    - stub 模式：不带头（网关侧 Stub 放行，保持本地联调零配置）。
    下游不可达 / 非 2xx / 解析失败 → 抛异常由 dispatch 兜底。
    """
    import httpx

    from .security import security

    headers = {}
    token = security.get_system_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"content": content, "type": memory_type, "importance": importance}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(f"{MEMORY_URL}/agentmemory/remember", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def dispatch(intent: str, request: AskRequest, slots: dict[str, Any] | None = None) -> dict[str, Any]:
    """按意图分发到内部能力端口，返回 result 字典（能力实现可逐步接入）。"""
    slots = slots or {}
    text = (request.message or "").strip() or (slots.get("text") or slots.get("content") or "")

    if intent == "job_match":
        resume_text = (
            (request.resume_text or "").strip()
            or (request.context or {}).get("resume_text") or ""
            or (slots.get("resume_text") or slots.get("resume") or "")
        )
        if not resume_text:
            return {
                "message": "请先提供简历内容",
                "status": "pending",
                "hint": "可通过上传简历（POST /v1/documents/convert）或在本请求中传入 resume_text / context.resume_text",
                "slots": slots,
            }
        try:
            from tatha.jobs import run_job_match_pipeline
            from tatha.core.config import job_top_n

            results, total = run_job_match_pipeline(resume_text=resume_text, top_n=job_top_n())
            matches = [r.model_dump() for r in results]
            return {
                "message": "已根据简历完成职位匹配",
                "status": "ok",
                "matches": matches,
                "total_evaluated": total,
                "slots": slots,
            }
        except Exception as e:
            return {"message": "职位匹配失败", "status": "error", "error": str(e), "slots": slots}
    if intent == "resume_upload":
        if text:
            try:
                extracted = _document_analysis("resume", text)
                if extracted is not None:
                    return {"message": "已解析简历结构化信息", "status": "ok", "extracted": extracted, "slots": slots}
                return {"message": "简历解析未返回结果", "status": "pending", "hint": "请检查 .env 中 OPENAI/DEEPSEEK 等 API Key 及 TATHA_DOCUMENT_ANALYSIS_BACKEND", "slots": slots}
            except Exception as e:
                return {"message": "简历解析失败", "status": "error", "error": str(e), "slots": slots}
        return {"message": "简历上传与解析服务开发中", "status": "pending", "hint": "V0 将接入 MarkItDown + 解析", "slots": slots}
    if intent == "poetry":
        if text:
            try:
                # 直接导入 chroma_poetry（独立模块，不依赖 llama_index）
                from tatha.retrieval.chroma_poetry import search_poems

                # 确定检索关键词
                search_query = text
                if _poetry_is_recommendation_query(text):
                    theme = random.choice(POETRY_RECOMMEND_THEMES)
                    search_query = theme

                # RAG 检索
                poems = search_poems(search_query, n_results=3)
                if poems:
                    # 用检索结果构建上下文，交给 LLM 生成推荐
                    context = "\n\n".join(
                        f"【{p['dynasty']}】{p['title']} — {p['author']}\n{p['content']}"
                        for p in poems
                    )
                    prompt = (
                        f"从以下诗词中挑选最合适的一首推荐给用户。用户查询：{text}\n\n"
                        f"候选诗词：\n{context}\n\n"
                        f"请以 JSON 格式返回：title（标题）、author（作者）、dynasty（朝代）、"
                        f"content（选其中最有代表性的两句）、theme（主题如思乡/送别/励志等）。只输出 JSON。"
                    )
                    try:
                        resp = llm_completion(
                            messages=[
                                {"role": "system", "content": "你是诗词推荐助手，只输出 JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                        )
                        resp_text = (resp.choices[0].message.content or "").strip()
                        # 清理 markdown 包裹
                        if "```" in resp_text:
                            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", resp_text)
                            if m:
                                resp_text = m.group(1).strip()
                        extracted = json.loads(resp_text)
                        return {"message": "已为您推荐诗词", "status": "ok", "extracted": extracted, "slots": slots}
                    except Exception:
                        # LLM 失败则直接返回检索结果
                        best = poems[0]
                        return {
                            "message": "已为您检索诗词",
                            "status": "ok",
                            "extracted": {
                                "title": best["title"],
                                "author": best["author"],
                                "dynasty": best["dynasty"],
                                "content": best["content"][:100],
                                "theme": search_query,
                            },
                            "slots": slots,
                        }
                return {"message": "未找到匹配的诗词", "status": "pending", "hint": "请尝试其他主题词", "slots": slots}
            except Exception as e:
                return {"message": "诗词检索失败", "status": "error", "error": str(e), "slots": slots}
        return {"message": "诗人/诗词推荐已就绪", "status": "pending", "hint": "请描述您想找的诗词主题，如「推荐一句思乡的诗」", "slots": slots}
    if intent == "credit":
        # 仅当消息像「信用报告/文档片段」时才调用解析；短句查询（如「查一下征信」）视为无正文
        if _credit_has_document_body(text):
            try:
                extracted = _document_analysis("credit", text)
                if extracted is not None:
                    return {"message": "已解析征信相关信息", "status": "ok", "extracted": extracted, "slots": slots}
                return {"message": "征信解析未返回结果", "status": "pending", "hint": "请检查 API Key 与 TATHA_DOCUMENT_ANALYSIS_BACKEND", "slots": slots}
            except Exception as e:
                return {"message": "征信解析失败", "status": "error", "error": str(e), "slots": slots}
        return {"message": "征信/验证服务开发中", "status": "pending", "hint": "请提供信用报告摘要或主体/报告类型/摘要等文本后再解析", "slots": slots}
    if intent == "mbti":
        from tatha.agents.mbti_analyzer import MBTITextAnalyzer, MIN_TEXT_LENGTH
        from tatha.agents.mbti_career_match import get_career_match

        if text and len(text.strip()) >= MIN_TEXT_LENGTH:
            try:
                analyzer = MBTITextAnalyzer()
                analysis = analyzer.analyze_text(text)
                if analysis.get("mbti_type") and analysis["mbti_type"] != "XXXX":
                    career = get_career_match(analysis["mbti_type"])
                    extracted = {**analysis, "career_match": career}
                    return {
                        "message": "已根据您的描述完成性格分析并给出职业建议",
                        "status": "ok",
                        "extracted": extracted,
                        "slots": slots,
                    }
                return {
                    "message": "已分析性格维度，建议补充更多描述以获得更稳定类型",
                    "status": "ok",
                    "extracted": analysis,
                    "slots": slots,
                }
            except Exception as e:
                return {"message": "人格测评分析失败", "status": "error", "error": str(e), "slots": slots}
        return {
            "message": "职业人格测评已就绪",
            "status": "pending",
            "hint": "请描述您的做事风格或发一段自述（至少20字），我会帮您分析性格类型并给出职业建议",
            "slots": slots,
        }
    if intent == "knowledge":
        if not text:
            return {
                "message": "知识库问答已就绪",
                "status": "pending",
                "hint": "请描述想查询的知识库内容，如「帮我查一下 xxx」",
                "slots": slots,
            }
        try:
            data = _call_knowledge_service(text)
            answer = (data.get("answer") or "").strip() or "知识库未返回回答"
            return {
                "message": "已从知识库检索到回答",
                "status": "ok",
                "answer": answer,
                "sources": data.get("sources") or [],
                "query": data.get("query"),
                "retrieval_mode": data.get("retrieval_mode"),
                "chunk_count": data.get("chunk_count"),
                "response_time_ms": data.get("response_time_ms"),
                "slots": slots,
            }
        except Exception as e:
            return {
                "message": "知识库查询失败",
                "status": "error",
                "error": str(e),
                "hint": f"请确认 DemoPeter 知识库服务已启动（TATHA_KNOWLEDGE_URL，默认 {KNOWLEDGE_URL}）",
                "slots": slots,
            }
    if intent == "memory":
        if not text:
            return {
                "message": "记忆服务已就绪",
                "status": "pending",
                "hint": "可以说「记住 xxx」让我写入记忆，或描述想回忆的内容如「之前关于 xxx 的记忆」",
                "slots": slots,
            }
        # 写入/检索分流：显式写入信号（LLM slots 或文本关键词）→ remember；否则 → search
        want_write = bool(
            slots.get("action") == "remember"
            or slots.get("write")
            or any(kw in text for kw in ("记住", "记下", "记着", "帮我记"))
        )
        if want_write:
            try:
                data = _remember_memory_service(text)
                memory = data.get("memory") or {}
                return {
                    "message": "已记住这条信息",
                    "status": "ok",
                    "memory": memory,
                    "remembered": bool(data.get("success")),
                    "content": memory.get("content") or text,
                    "slots": slots,
                }
            except Exception as e:
                return {
                    "message": "记忆写入失败",
                    "status": "error",
                    "error": str(e),
                    "hint": f"请确认 agentmemory 网关已启动（TATHA_MEMORY_URL，默认 {MEMORY_URL}；引擎 :3111 需在线）",
                    "slots": slots,
                }
        try:
            data = _call_memory_service(text)
            # mem::search 返回 {results: [{observation, score}]}，兼容旧式 {memories: [...]}
            results = data.get("results") or data.get("memories") or []
            memories = [
                (item.get("observation") or item)
                for item in results
                if isinstance(item, dict)
            ]
            answer = (data.get("answer") or "").strip()
            return {
                "message": "已从记忆库检索到相关内容",
                "status": "ok",
                "memories": memories[:10],
                "answer": answer,
                "query": text,
                "slots": slots,
            }
        except Exception as e:
            return {
                "message": "记忆检索失败",
                "status": "error",
                "error": str(e),
                "hint": f"请确认 agentmemory 网关已启动（TATHA_MEMORY_URL，默认 {MEMORY_URL}；引擎 :3111 需在线）",
                "slots": slots,
            }
    return {"message": "暂未识别到明确意图", "status": "unknown", "received": (request.message or "")[:100]}


def handle_ask(request: AskRequest) -> AskResponse:
    """单入口处理：解析意图（LLM 主路径 + 规则回退）→ 分发 → 统一响应。"""
    intent, confidence, slots = parse_intent(request.message)
    result = dispatch(intent, request, slots)
    result["confidence"] = confidence
    suggestions = []
    if intent == "unknown":
        suggestions.append("可以说：帮我匹配职位、上传简历、推荐一句诗、查一下知识库、回忆一下 xxx 等")
    return AskResponse(intent=intent, result=result, suggestions=suggestions)
