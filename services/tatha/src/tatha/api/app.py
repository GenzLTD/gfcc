"""
Tatha 主仓 HTTP 入口：供 ZeroClaw 助理 Tool 调用。

架构：单入口 + 中央大脑。用户/助理只调用一个入口（POST /v1/ask），
需求由中央大脑解析并分发到内部各能力端口（解析、匹配、诗人 RAG、征信等），
内部实现与端口对用户不可见。

文档上传：POST /v1/documents/convert 使用 MarkItDown 转 Markdown，并可选做结构化提取（如简历）。

可选演示页：GET /demo.html 返回单文件 demo.html（与 API 同源，便于浏览器直接体验匹配结果）。
"""
import io
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .auth import AuthContext, get_auth, get_bearer_token
from .quota import (
    RESOURCE_ASK,
    RESOURCE_JOB_MATCH,
    RESOURCE_RAG,
    RESOURCE_RESUME_PARSE,
    consume,
    clamp_top_n,
    get_remaining,
)
from .security import TIER_TO_TATHA, is_super_admin, security
from .region import get_region_response
from .schemas import (
    AskRequest,
    AskResponse,
    AuthLoginRequest,
    AuthRegisterRequest,
    DocumentConvertResponse,
    JobMatchRequest,
    JobMatchResponse,
    RagQueryRequest,
    RagQueryResponse,
)
from .central_brain import handle_ask


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """运行时系统自动签发：启动即就绪系统令牌并审计（HMAC 严格模式才生效）。

    签发全程无人干预；过期由 SystemMinter 惰性续签。系统令牌等同超管权限，
    仅供内部服务间调用，不对外暴露。
    """
    security.bootstrap()
    yield


app = FastAPI(
    title="Tatha API",
    description="Tatha 主仓：单入口 + 中央大脑，简历解析、匹配、诗人/诗词 RAG",
    version="0.1.0",
    lifespan=_lifespan,
)

# 超管签发令牌的合法档位（与网关协议 §1 档位键一致）
_MINT_ALLOWED_TIERS = ("free", "basic", "pro", "admin")


class AdminMintRequest(BaseModel):
    """超管签发令牌请求（/v1/admin/tokens）。"""

    sub: str
    tier: str = "free"
    roles: list[str] = []
    ttl: int = 3600


# 客户端非 UTF-8 编码回退序列（Windows PowerShell 5.1 / curl.exe 中文发送常见 GBK）
_FALLBACK_ENCODINGS = ("gbk", "gb18030", "latin-1")


def _normalize_json_body(body: bytes) -> bytes | None:
    """
    把客户端发送的 JSON 请求体规范化为 UTF-8 字节。

    返回 None 表示 body 已是合法 UTF-8 JSON（无需转换）；否则返回按回退编码
    解码成功后重新编码的 UTF-8 JSON 字节。若所有编码都无法解析为合法 JSON，
    同样返回 None（交由 FastAPI 正常返回 422）。
    """
    try:
        text = body.decode("utf-8")
        json.loads(text)
        return None  # 已是 UTF-8 合法 JSON
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    for enc in _FALLBACK_ENCODINGS:
        try:
            text = body.decode(enc)
            json.loads(text)
            return text.encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


@app.middleware("http")
async def ensure_utf8_json(request: Request, call_next):
    """
    服务端兜底中文解码（作为服务提供方的义务，不依赖客户端行为）：

    1) 请求侧：客户端以非 UTF-8（Windows 中文系统默认 GBK / 老 curl 的 Latin-1）
       发送 JSON 中文时，回退解码并规范化为 UTF-8，避免服务端收到乱码导致
       意图识别失败。
    2) 响应侧：所有 JSON 响应追加 charset=utf-8，避免 Windows PowerShell 5.1
       按 Latin-1 解码响应导致中文乱码。
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        ct = request.headers.get("content-type", "")
        if ct.startswith("application/json"):
            body = await request.body()
            if body:
                normalized = _normalize_json_body(body)
                if normalized is not None and normalized != body:
                    # Starlette 0.52+ 的 BaseHTTPMiddleware 用 _CachedRequest.wrapped_receive
                    # 转发 body：一旦 request.body() 被调用，_body 会被缓存并直接传给下游。
                    # 因此改写 _body 即可让下游 request.json() 拿到规范化的 UTF-8 字节。
                    request._body = normalized

    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset=" not in ct:
        response.headers["content-type"] = ct + "; charset=utf-8"
    return response


# 项目根目录（便于同源提供 demo.html，避免 CORS；app.py 在 src/tatha/api/）
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


@app.get("/health")
def health():
    """探活：唯一对外端口下的健康检查。"""
    return {"status": "ok", "service": "tatha"}


def _serve_html(filename: str):
    path = os.path.join(_ROOT, filename)
    if not os.path.isfile(path):
        return PlainTextResponse(f"{filename} not found", status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def serve_index():
    """认证订阅入口页：三档（免费/Basic/Pro），参考 ServBay 定价页形态。"""
    return _serve_html("index.html")


@app.get("/demo.html", response_class=HTMLResponse)
def serve_demo():
    """可选演示页：单文件 HTML，调用 /v1/ask 与 /v1/jobs/match 并在页面展示结果。仅用于开发期直观感受。"""
    return _serve_html("demo.html")


@app.get("/auth.html", response_class=HTMLResponse)
def serve_auth():
    """登录/注册页：Web 端登录注册测试用，当前为演示桩，未对接真实认证。"""
    return _serve_html("auth.html")


@app.get("/v1/region")
def region(request: Request):
    """
    按请求 IP 返回地区与定价，供订阅页展示币种与价格。无需鉴权。
    国内（CN）返回 CNY + pricing_cn，境外返回 USD + pricing_intl。
    """
    return get_region_response(request)


def _supabase_auth_enabled() -> bool:
    """Phase 2: Supabase Auth 已配置时返回 True。"""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def _supabase_sign_in(email: str, password: str) -> dict:
    """
    Phase 2 接入点：调用 Supabase Auth REST API 做真实登录。
    环境变量：SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    文档：https://supabase.com/docs/reference/javascript/auth-signinwithpassword
    """
    import urllib.request, json as _json
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/token?grant_type=password"
    body = _json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read().decode())
    return data  # contains access_token, user, etc.


def _supabase_sign_up(email: str, password: str) -> dict:
    """
    Phase 2 接入点：调用 Supabase Auth REST API 做真实注册。
    """
    import urllib.request, json as _json
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/signup"
    body = _json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read().decode())
    return data


@app.post("/v1/auth/login")
def auth_login(request: AuthLoginRequest):
    """
    登录：
    - Phase 1（default）：演示桩，格式校验后返回 demo-token。
    - Phase 2（配置 SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY）：转发 Supabase Auth，返回真实 JWT。
    """
    if _supabase_auth_enabled():
        try:
            data = _supabase_sign_in(request.email or "", request.password or "")
            token = data.get("access_token")
            if not token:
                err = data.get("error_description") or data.get("msg") or "Login failed"
                raise HTTPException(status_code=401, detail=err)
            return {"ok": True, "message": "Signed in", "token": token}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=401, detail=str(e))
    # 签发只走"运行时自动 + 超管例外"（SystemMinter）：login/register 不签发，不被人为左右；
    # 真实用户令牌由外部签发方（Go 8207 / Rust 网关 / Supabase）签发后由 ethos 验签。
    # Demo stub (Phase 1)
    return {
        "ok": True,
        "message": "登录成功（演示用，未对接真实认证）",
        "token": "demo-token-" + (request.email or "").replace("@", "-at-")[:32],
    }


@app.post("/v1/auth/register")
def auth_register(request: AuthRegisterRequest):
    """
    注册：
    - Phase 1（default）：演示桩，格式校验后返回 demo-token。
    - Phase 2（配置 SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY）：转发 Supabase Auth 注册。
    """
    if _supabase_auth_enabled():
        try:
            data = _supabase_sign_up(request.email or "", request.password or "")
            token = data.get("access_token")
            if not token:
                err = data.get("error_description") or data.get("msg") or "Registration failed"
                raise HTTPException(status_code=400, detail=err)
            return {"ok": True, "message": "Account created", "token": token}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    # 签发只走"运行时自动 + 超管例外"（SystemMinter）：login/register 不签发，不被人为左右；
    # 真实用户令牌由外部签发方（Go 8207 / Rust 网关 / Supabase）签发后由 ethos 验签。
    # Demo stub (Phase 1)
    return {
        "ok": True,
        "message": "注册成功（演示用，未对接真实认证）",
        "token": "demo-token-" + (request.email or "").replace("@", "-at-")[:32],
    }


@app.post("/v1/admin/tokens")
def admin_mint_token(
    request: AdminMintRequest,
    authorization: str | None = Header(None, alias="Authorization"),
):
    """
    超管签发令牌（运行时系统自动签发的受控补充，仅超管/系统主体可用）：
    - 必须处于 HMAC 严格模式（ETHOS_AUTH_SECRET 已配置），未配置时 403；
    - 请求者须为超管/系统主体（tier=admin 或 roles 含 admin/super_admin/system）；
    - 签发用与 ethos 验签相同的 secret，签出标准 JWT 可被 ethos 直接验通；
    - 签发成功落审计 admin.mint（可溯源）。
    """
    token = get_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing or invalid authorization")
    if not security.hmac_enabled:
        raise HTTPException(
            status_code=403,
            detail="admin mint 需配置 ETHOS_AUTH_SECRET（HMAC 严格模式）",
        )
    principal = security.verify_principal(token)
    if principal is None or not is_super_admin(principal):
        raise HTTPException(
            status_code=403,
            detail="需要超级管理员权限（tier=admin 或 roles 含 admin/super_admin/system）",
        )
    sub = (request.sub or "").strip()
    if not sub:
        raise HTTPException(status_code=422, detail="sub 不能为空")
    tier = (request.tier or "free").lower()
    if tier not in _MINT_ALLOWED_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"tier 必须是 {'/'.join(_MINT_ALLOWED_TIERS)} 之一",
        )
    ttl = max(60, request.ttl)
    roles = list(request.roles or [])
    issued = security.mint_for(sub, tier, roles, ttl)
    security.audit(
        auth=AuthContext(
            user_id=principal.user_id,
            tier=TIER_TO_TATHA.get(principal.tier.value, "free"),
        ),
        action="admin.mint",
        resource="system",
        status="ok",
        request_id="",
        detail=f"mint sub={sub} tier={tier} roles={roles}",
    )
    return {
        "ok": True,
        "token": issued,
        "sub": sub,
        "tier": tier,
        "roles": roles,
        "ttl": ttl,
    }


def _quota_exceeded_response():
    return HTTPException(
        status_code=429,
        detail={
            "code": "quota_exceeded",
            "message": "当日配额已用尽，请升级后继续使用。",
        },
    )


@app.post("/v1/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    auth: AuthContext = Depends(get_auth),
    req: Request = None,
):
    """
    单入口：用户需求由此进入，中央大脑解析意图并分发到内部端口，返回统一 JSON。
    安全闭环（ethos）：认证（get_auth）→ 鉴权（authorize "ask"）→ 审计（每次调用落 SQLite）。
    V1 需鉴权与配额。
    """
    request_id = req.headers.get("x-request-id", "") if req else ""

    # 1. 鉴权
    decision = security.authorize(auth, "ask")
    if not decision.allow:
        security.audit(
            auth=auth, action="ask", status="denied",
            request_id=request_id, detail=decision.reason,
        )
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": decision.reason},
        )

    # 2. 配额
    if not consume(auth.user_id, auth.tier, RESOURCE_ASK):
        security.audit(auth=auth, action="ask", status="quota_exceeded", request_id=request_id)
        raise _quota_exceeded_response()

    # 3. 执行业务 + 审计（无论成败均记录）
    start = time.time()
    resp: AskResponse | None = None
    try:
        resp = handle_ask(request)
        return resp
    finally:
        security.audit(
            auth=auth,
            action="ask",
            intent=resp.intent if resp else "",
            status="ok" if resp else "error",
            latency_ms=int((time.time() - start) * 1000),
            quota_after=get_remaining(auth.user_id, auth.tier, RESOURCE_ASK),
            request_id=request_id,
        )


@app.post("/v1/documents/convert", response_model=DocumentConvertResponse)
async def documents_convert(
    file: UploadFile = File(..., description="待转换文档（PDF/Word/Excel 等）"),
    document_type: str | None = Form("resume", description="文档类型：resume / poetry / credit，用于选择提取器"),
    auth: AuthContext = Depends(get_auth),
):
    """
    高效解析标准流程：MarkItDown 多格式 → Markdown，再按 document_type 做可选结构化提取。
    V1 需鉴权与配额（resume 类型计入简历解析配额）。
    """
    dtype = (document_type or "resume").strip().lower() or "resume"
    if dtype == "resume" and not consume(auth.user_id, auth.tier, RESOURCE_RESUME_PARSE):
        raise _quota_exceeded_response()
    try:
        content = await file.read()
    except Exception as e:
        return DocumentConvertResponse(markdown="", error=f"读取文件失败: {e}")
    if not content:
        return DocumentConvertResponse(markdown="", error="文件为空")

    try:
        from tatha.ingest.markitdown_convert import stream_to_markdown

        markdown = stream_to_markdown(
            io.BytesIO(content),
            filename=file.filename or None,
        )
    except Exception as e:
        return DocumentConvertResponse(markdown="", error=f"MarkItDown 转换失败: {e}")

    extracted = None
    if dtype and markdown:
        try:
            from tatha.api.central_brain import _document_analysis
            extracted = _document_analysis(dtype, markdown)
        except Exception as e:
            return DocumentConvertResponse(
                markdown=markdown,
                document_type=dtype,
                error=f"结构化提取失败: {e}",
            )

    return DocumentConvertResponse(
        markdown=markdown,
        document_type=dtype,
        extracted=extracted,
    )


@app.post("/v1/jobs/match", response_model=JobMatchResponse)
def jobs_match(request: JobMatchRequest, auth: AuthContext = Depends(get_auth)):
    """
    职位匹配流水线：拉取职位 → 简历 vs 职位 LLM 打分 → 按综合分排序返回 Top-N。V1 需鉴权与配额。
    top_n 按档位限制（Free≤3，Basic≤5，Pro≤20）；超配额返回 429。
    """
    if not consume(auth.user_id, auth.tier, RESOURCE_JOB_MATCH):
        raise _quota_exceeded_response()
    top_n = clamp_top_n(auth.tier, request.top_n or 5)
    try:
        from tatha.jobs import run_job_match_pipeline

        results, total = run_job_match_pipeline(
            resume_text=request.resume_text,
            top_n=top_n,
            source_id=request.source,
        )
        return JobMatchResponse(
            matches=[r.model_dump() for r in results],
            total_evaluated=total,
        )
    except Exception as e:
        return JobMatchResponse(matches=[], total_evaluated=0, error=str(e))


@app.post("/v1/rag/query", response_model=RagQueryResponse)
def rag_query(request: RagQueryRequest, auth: AuthContext = Depends(get_auth)):
    """
    对私有索引做 RAG 查询：仅使用已构建的命名空间索引，数据不离开本地。V1 需鉴权与配额。
    """
    if not consume(auth.user_id, auth.tier, RESOURCE_RAG):
        raise _quota_exceeded_response()
    try:
        from tatha.retrieval import get_query_engine
        engine = get_query_engine(namespace=request.namespace)
        answer = str(engine.query(request.query))
        return RagQueryResponse(answer=answer, namespace=request.namespace)
    except FileNotFoundError:
        return RagQueryResponse(
            answer="",
            namespace=request.namespace,
            error=f"索引不存在。请先用 build_index_from_dir 或 build_index_from_documents 构建 namespace={request.namespace} 的索引（存储于 .data/indices/<namespace>）。",
        )
    except Exception as e:
        return RagQueryResponse(
            answer="",
            namespace=request.namespace,
            error=str(e),
        )


# ============ IoT 设备控制（MVP 暂不启用）============
# 以下路由依赖 src/tatha/iot/ 模块（尚未实现），MVP 阶段注释掉
#
# @app.post("/api/v1/intent-parse", ...)
# @app.post("/api/v1/device/command", ...)
# @app.post("/api/v1/scene/trigger", ...)
# @app.get("/api/v1/mqtt/status")
# @app.post("/api/v1/mqtt/connect")
