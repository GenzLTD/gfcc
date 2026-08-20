"""
Outlook / Microsoft Graph OAuth2 客户端
支持: 授权→自动刷新Token→收发邮件→日历→联系人
Token 持久化到 db/outlook_tokens.json，长期有效无需重新登录
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from config.settings import config

logger = logging.getLogger(__name__)

# ── OAuth2 端点 ────────────────────────────────────────────
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# ── 默认授权范围 ───────────────────────────────────────────
DEFAULT_SCOPES = [
    "offline_access",                          # 获取 refresh_token
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/User.Read",
]
# 可选扩展:
#   "https://graph.microsoft.com/Mail.ReadWrite"
#   "https://graph.microsoft.com/Calendars.ReadWrite"
#   "https://graph.microsoft.com/Contacts.Read"


class OutlookClient:
    """Microsoft Graph API 客户端，自动管理 token 生命周期"""

    def __init__(self):
        self._check_config()
        self._token_path = Path(config.OUTLOOK_TOKEN_PATH)
        self._tokens: dict = {}
        self._load_tokens()

    # ═══════════════════════════════════════════
    #  公共 API：授权
    # ═══════════════════════════════════════════

    @staticmethod
    def get_auth_url(redirect_uri: str | None = None) -> str:
        """生成 Microsoft 授权页面 URL，用户在浏览器中打开后授权"""
        params = {
            "client_id": config.OUTLOOK_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri or config.OUTLOOK_REDIRECT_URI,
            "scope": " ".join(DEFAULT_SCOPES),
            "response_mode": "query",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str | None = None) -> bool:
        """用授权码换取 token 并持久化保存"""
        data = {
            "client_id": config.OUTLOOK_CLIENT_ID,
            "client_secret": config.OUTLOOK_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri or config.OUTLOOK_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        resp = requests.post(TOKEN_URL, data=data, timeout=15)
        resp.raise_for_status()
        tokens = resp.json()
        tokens["obtained_at"] = time.time()
        self._tokens = tokens
        self._save_tokens()
        logger.info("Outlook 授权成功")
        return True

    @property
    def is_authorized(self) -> bool:
        return "access_token" in self._tokens

    # ═══════════════════════════════════════════
    #  公共 API：邮件
    # ═══════════════════════════════════════════

    def list_mails(self, folder: str = "inbox", top: int = 10,
                   select: str = "subject,from,receivedDateTime,bodyPreview",
                   search: str = "") -> list[dict]:
        """获取邮件列表"""
        endpoint = f"/me/mailFolders/{folder}/messages"
        params: dict[str, Any] = {"$top": top, "$select": select,
                                    "$orderby": "receivedDateTime DESC"}
        if search:
            params["$search"] = f'"{search}"'
        return self._graph_get(endpoint, params).get("value", [])

    def get_mail(self, message_id: str) -> dict:
        """获取单封邮件详情"""
        return self._graph_get(f"/me/messages/{message_id}")

    def send_mail(self, *, to: str, subject: str, body: str,
                  body_type: str = "Text") -> dict:
        """发送邮件"""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": [{"emailAddress": {"address": addr.strip()}}
                                 for addr in to.split(",")],
            },
            "saveToSentItems": "true",
        }
        return self._graph_post("/me/sendMail", payload)

    def mark_read(self, message_id: str) -> dict:
        """标记为已读"""
        return self._graph_patch(f"/me/messages/{message_id}",
                                  {"isRead": True})

    def delete_mail(self, message_id: str) -> dict:
        """删除邮件（移到已删除）"""
        return self._graph_delete(f"/me/messages/{message_id}")

    def move_mail(self, message_id: str, folder_id: str) -> dict:
        """移动邮件到指定文件夹"""
        return self._graph_post(f"/me/messages/{message_id}/move",
                                {"destinationId": folder_id})

    # ═══════════════════════════════════════════
    #  公共 API：用户信息
    # ═══════════════════════════════════════════

    def get_profile(self) -> dict:
        """获取当前用户信息"""
        return self._graph_get("/me")

    def get_mail_folders(self) -> list[dict]:
        """获取邮件文件夹列表"""
        return self._graph_get("/me/mailFolders").get("value", [])

    # ═══════════════════════════════════════════
    #  Token 管理
    # ═══════════════════════════════════════════

    def _get_valid_token(self) -> str:
        """获取有效的 access_token，过期自动刷新"""
        if not self._tokens:
            raise RuntimeError("未授权，请先执行授权流程")

        expires_in = self._tokens.get("expires_in", 3600)
        obtained = self._tokens.get("obtained_at", 0)
        if time.time() - obtained > expires_in - 60:
            # 提前 60 秒刷新
            self._refresh_token()
        return self._tokens["access_token"]

    def _refresh_token(self) -> None:
        """使用 refresh_token 获取新 token"""
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("没有 refresh_token，需要重新授权")

        data = {
            "client_id": config.OUTLOOK_CLIENT_ID,
            "client_secret": config.OUTLOOK_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        resp = requests.post(TOKEN_URL, data=data, timeout=15)
        resp.raise_for_status()
        new_tokens = resp.json()
        # refresh_token 可能不会每次返回，保留旧的
        if "refresh_token" not in new_tokens:
            new_tokens["refresh_token"] = refresh_token
        new_tokens["obtained_at"] = time.time()
        self._tokens = new_tokens
        self._save_tokens()
        logger.info("Outlook token 已刷新")

    def _load_tokens(self) -> None:
        if self._token_path.exists():
            self._tokens = json.loads(self._token_path.read_text(encoding="utf-8"))

    def _save_tokens(self) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(
            json.dumps(self._tokens, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # 限制文件权限（仅当前用户读写）
        try:
            self._token_path.chmod(0o600)
        except Exception:
            pass

    def _check_config(self) -> None:
        missing = []
        if not config.OUTLOOK_CLIENT_ID:
            missing.append("OUTLOOK_CLIENT_ID")
        if not config.OUTLOOK_CLIENT_SECRET:
            missing.append("OUTLOOK_CLIENT_SECRET")
        if missing:
            raise ValueError(f"缺少配置: {', '.join(missing)}，请在 .env 中设置")

    # ═══════════════════════════════════════════
    #  底层 Graph API 调用
    # ═══════════════════════════════════════════

    def _graph_get(self, path: str, params: dict | None = None) -> dict:
        return self._graph_request("GET", path, params=params)

    def _graph_post(self, path: str, payload: dict) -> dict:
        return self._graph_request("POST", path, payload=payload)

    def _graph_patch(self, path: str, payload: dict) -> dict:
        return self._graph_request("PATCH", path, payload=payload)

    def _graph_delete(self, path: str) -> dict:
        return self._graph_request("DELETE", path)

    def _graph_request(self, method: str, path: str,
                       params: dict | None = None,
                       payload: dict | None = None) -> dict:
        token = self._get_valid_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{GRAPH_BASE}{path}"
        resp = requests.request(method, url, headers=headers,
                                params=params, json=payload, timeout=30)
        if resp.status_code == 204:  # no content
            return {}
        resp.raise_for_status()
        return resp.json()
