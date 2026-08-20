"""DemoPeter × ethos：认证 / 鉴权 / 审计统一接入（双模）。

模式：
- 未配置 ETHOS_AUTH_SECRET → ethos StubVerifier：本地零登录体验保持（匿名 admin，全放行）；
- 配置 ETHOS_AUTH_SECRET → HMAC 严格模式：验签标准 JWT + 档位鉴权 + SQLite 审计。
  与 Tatha（同一 secret）互通：Tatha 智慧大脑持系统令牌（svc:tatha，tier=admin）可直接调度。

接入（web_dashboard.py 启动处一行）：
    from src.ethos_bootstrap import init_ethos_guard
    init_ethos_guard(app)

审计库：<DB_DIR>/ethos_audit.db（ethos 统一结构；旧 tenet 表启动时自动迁移保留，见网关协议 §4.4）。

豁免路由（直通不鉴权）：
- /api/health/*            —— 健康探针
- /api/system/check        —— 系统自检
- /api/webhook/gitea       —— 已有 Gitea HMAC 签名
- /auth/outlook/*          —— 非 /api 前缀天然豁免
"""
from __future__ import annotations

import os
from functools import lru_cache

from flask import Flask, jsonify, request

from ethos.security import SecurityProvider, init_security

from config.settings import config

# 档位策略：scope → 最低档位（与 Tatha _TIER_POLICY 对齐）
TIER_POLICY: dict[str, str] = {
    "search": "free",        # 数据读取 / 列表 / 索引检索
    "rag.query": "pro",      # RAG 问答 / 流式 / 报告生成
    "memory.write": "pro",   # 导入 / 上传 / 删除 / 索引扫描
    "admin": "admin",        # 重置 / 清空类管理操作
}

# 豁免前缀：直通不鉴权（见模块 docstring）
EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/health/",
    "/api/system/check",
    "/api/webhook/gitea",
)

# 精确路径 → action（优先匹配）
_EXACT_ACTIONS: dict[str, str] = {
    "/api/rag/query": "rag.query",
    "/api/rag/stream": "rag.query",
    "/api/reports/generate": "rag.query",
    "/api/documents/import": "memory.write",
    "/api/documents/upload": "memory.write",
    "/api/d-index/scan": "admin",
    "/api/d-index/clear": "admin",
    "/api/d-index/checkpoint/reset": "admin",
}

# 前缀 → action（兜底；其余 /api/* 一律按只读 search 处理）
_PREFIX_ACTIONS: dict[str, str] = {
    "/api/documents": "search",
    "/api/d-index/": "search",
    "/api/stats": "search",
    "/api/reports": "search",
}


def _action_for(path: str) -> str:
    """路径 → 最小 action（鉴权粒度，见接入清单）。"""
    if path in _EXACT_ACTIONS:
        return _EXACT_ACTIONS[path]
    for prefix, action in _PREFIX_ACTIONS.items():
        if path.startswith(prefix):
            return action
    return "search"


@lru_cache(maxsize=1)
def get_security() -> SecurityProvider:
    """惰性装配 ethos（secret 取自 ETHOS_AUTH_SECRET，空 → Stub 放行）。

    测试或改配置后可调用 get_security.cache_clear() 重建。
    """
    return init_security(
        secret=os.getenv("ETHOS_AUTH_SECRET") or None,
        tier_policy=TIER_POLICY,
        audit_db=str(config.DB_DIR / "ethos_audit.db"),
    )


def _extract_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return ""


def init_ethos_guard(app: Flask) -> SecurityProvider:
    """注册 before_request：统一认证 / 鉴权 / 审计 /api/*（豁免清单直通）。

    返回装配好的 SecurityProvider（便于按需复用 sec 实例）。
    """

    @app.before_request
    def _ethos_guard() -> None:
        path = request.path
        if not path.startswith("/api/") or path.startswith(EXEMPT_PREFIXES):
            return None
        sec = get_security()
        ctx = sec.verify(_extract_token())
        if not ctx.ok:
            return jsonify({"detail": ctx.error or "missing or invalid authorization"}), 401
        action = _action_for(path)
        try:
            sec.require(ctx, action)
        except PermissionError as exc:
            return jsonify({"detail": str(exc)}), 403
        sec.audit(action, principal=ctx.principal, resource=path)
        return None

    return get_security()
