"""令牌验证器（ethos 是纯验证者——不签发，只验签）。

设计要点：
- 默认支持标准 JWT HS256（对应 zervi-rust auth-service / Go 统一认证体系）。
- Claims 宽容解析：sub / user_id / uid 都认，role / roles / tier 都认，
  与 Rust(Claims{sub,role})、Go(Claims{user_id,roles[]}) 两套令牌格式兼容。
- 支持异步验证（asyncio 友好），同步调用用 `verify`（内部转 await）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Mapping, Optional

from ._jwt import b64url_decode, b64url_encode, split_jwt
from ..models import AuthContext, Principal, Tier

# Claims 中识别"档位"的键（按优先级尝试）
_TIER_KEYS = ("tier", "plan", "level")
# Claims 中识别"角色"的键
_ROLE_KEYS = ("roles", "role", "authorities")
# Claims 中识别"用户 id"的键
_SUB_KEYS = ("sub", "user_id", "uid")


def _to_tier(value: Any) -> Tier:
    """把 Claims 里的档位值规整到统一 Tier 枚举（宽容匹配）。"""
    if value is None:
        return Tier.FREE
    s = str(value).strip().lower()
    for t in Tier:
        if s == t.value:
            return t
    # 兼容常见别名
    aliases = {
        "standard": Tier.BASIC,
        "gold": Tier.PRO,
        "vip": Tier.PRO,
        "super_admin": Tier.ADMIN,
        "root": Tier.ADMIN,
    }
    if s in aliases:
        return aliases[s]
    # basic+ 集合
    if s in ("basic", "bronze", "starter"):
        return Tier.BASIC
    if s in ("pro", "premium", "silver"):
        return Tier.PRO
    return Tier.FREE


def _first_of(claims: Mapping[str, Any], keys: tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        if k in claims and claims[k] is not None:
            return claims[k]
    return None


class TokenVerifier:
    """抽象基类：所有验证器的统一接口。

    - ``verify(token)``：同步验证（主接口，供 Flask 等同步框架）。
    - ``await averify(token)``：异步验证（Sanic/FastAPI 等事件循环内使用）。
    """

    name: str = "base"

    def verify(self, token: str) -> AuthContext:
        """同步验证入口。子类实现。"""
        raise NotImplementedError

    async def averify(self, token: str) -> AuthContext:
        """默认异步实现：在事件循环内调用同步 verify（避免线程阻塞事件循环）。

        子类若本身是 IO 密集（如远程验证），可覆盖为真异步。
        """
        return self.verify(token)


class HmacJwtVerifier(TokenVerifier):
    """HS256 标准 JWT 验证器（纯验证者，不签发）。

    兼容 zervi-rust / Go 统一认证签发的令牌：
    - 支持单个或多个 secret（轮换期双 secret 并存）。
    - Claims 键宽容（sub/user_id、roles/role、tier/plan）。
    """

    name = "jwt-hs256"

    def __init__(self, secret: str, extra_secrets: Optional[list[str]] = None) -> None:
        if not secret:
            raise ValueError("HmacJwtVerifier 需要 secret（HS256 对称密钥）")
        self._secret = secret.encode("utf-8")
        self._extra = [s.encode("utf-8") for s in (extra_secrets or [])]

    # -- 验签 -------------------------------------------------------------- #

    def _check_signature(self, signing_input: bytes, sig_b64: str, secret: bytes) -> bool:
        try:
            sig = b64url_decode(sig_b64)
        except Exception:
            return False
        expected = hmac.new(secret, signing_input, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)

    def _decode_claims(self, token: str) -> Optional[Dict[str, Any]]:
        header_b64, payload_b64, sig_b64 = split_jwt(token)
        # 校验 header 算法（防 alg=none / 混淆攻击）
        try:
            header = json.loads(b64url_decode(header_b64))
        except Exception:
            return None
        alg = str(header.get("alg", ""))
        if alg not in ("HS256",):
            return None  # 只接受 HS256，拒绝 none / HS384 等
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        secrets = [self._secret, *self._extra]
        if not any(self._check_signature(signing_input, sig_b64, s) for s in secrets):
            return None
        try:
            claims = json.loads(b64url_decode(payload_b64))
        except Exception:
            return None
        if not isinstance(claims, dict):
            return None
        return claims

    # -- 身份解析 ---------------------------------------------------------- #

    @staticmethod
    def _build_principal(claims: Dict[str, Any]) -> Principal:
        sub = str(_first_of(claims, _SUB_KEYS) or "")
        roles = _first_of(claims, _ROLE_KEYS)
        if isinstance(roles, str):
            role_list = [roles] if roles else []
        elif isinstance(roles, list):
            role_list = [str(r) for r in roles]
        else:
            role_list = []
        perms = claims.get("permissions") or claims.get("scope") or claims.get("scopes") or []
        if isinstance(perms, str):
            perm_list = [p.strip() for p in perms.replace(",", " ").split() if p.strip()]
        elif isinstance(perms, list):
            perm_list = [str(p) for p in perms]
        else:
            perm_list = []
        tier_raw = _first_of(claims, _TIER_KEYS) or (role_list[0] if role_list else None)
        return Principal(
            sub=sub,
            tier=_to_tier(tier_raw),
            roles=role_list,
            permissions=perm_list,
            tenant_type=claims.get("tenant_type") or claims.get("tenant"),
            username=claims.get("username") or claims.get("name"),
            claims=dict(claims),
            exp=_to_int(claims.get("exp")),
            iat=_to_int(claims.get("iat")),
        )

    # -- 验证入口 ---------------------------------------------------------- #

    def verify(self, token: str) -> AuthContext:
        ctx = AuthContext(token=token, verifier=self.name)
        if not token:
            ctx.error = "missing token"
            return ctx
        claims = self._decode_claims(token)
        if claims is None:
            ctx.error = "invalid signature or malformed token"
            return ctx
        # 过期校验（宽容：无 exp 视为不校验，与 tenet validate_exp=False 对齐）
        exp = _to_int(claims.get("exp"))
        if exp is not None and exp < time.time():
            ctx.error = "token expired"
            return ctx
        ctx.principal = self._build_principal(claims)
        ctx.verified = True
        return ctx


class StubVerifier(TokenVerifier):
    """本地联调桩：无 secret 时的放行模式（等价 tenet stub 认证）。

    不校验签名，仅解析出 principal；主要用于无密钥的本地演示。
    """

    name = "stub"

    def __init__(self, default_tier: Tier = Tier.ADMIN) -> None:
        self._default_tier = default_tier

    def verify(self, token: str) -> AuthContext:
        ctx = AuthContext(token=token, verifier=self.name)
        claims: Dict[str, Any] = {}
        # 尝试按 JWT 解析（若 token 恰好是 JWT，则读出身份；否则视为匿名 admin）
        try:
            _, payload_b64, _ = split_jwt(token)
            payload = json.loads(b64url_decode(payload_b64))
            if isinstance(payload, dict):
                claims = payload
        except Exception:
            claims = {"sub": "stub-anon"}
        ctx.principal = HmacJwtVerifier._build_principal(claims)
        if not ctx.principal.sub:
            ctx.principal = Principal(sub="stub-anon", tier=self._default_tier)
        else:
            # 保留解析出的身份，但档位统一为 stub 默认档（演示放开权限）
            ctx.principal = Principal(
                sub=ctx.principal.sub,
                tier=self._default_tier,
                roles=ctx.principal.roles,
                permissions=["*"],
                claims=ctx.principal.claims,
            )
        ctx.verified = True
        return ctx


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
