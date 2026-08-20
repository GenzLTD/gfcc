"""
Notion API 客户端 — 负责向 Notion 读写数据
支持: 创建/更新页面、操作数据库、追加内容块
"""
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from config.settings import config

logger = logging.getLogger(__name__)


class NotionClient:
    """Notion API 封装"""

    BASE_URL = "https://api.notion.com/v1"
    API_VERSION = "2022-06-28"

    def __init__(self, token: str | None = None):
        self.token = token or config.NOTION_TOKEN
        if not self.token:
            raise ValueError("Notion Token 未配置，请在 .env 中设置 NOTION_TOKEN")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
        })

    # ==================== 数据库操作 ====================

    def create_database(self, parent_page_id: str, title: str,
                        properties: dict) -> dict:
        """在指定页面下创建一个数据库"""
        payload: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        return self._post("/databases", payload)

    def query_database(self, database_id: str, filter_obj: dict | None = None,
                       sorts: list | None = None, page_size: int = 50) -> dict:
        """查询数据库"""
        payload: dict[str, Any] = {"page_size": page_size}
        if filter_obj:
            payload["filter"] = filter_obj
        if sorts:
            payload["sorts"] = sorts
        return self._post(f"/databases/{database_id}/query", payload)

    # ==================== 页面操作 ====================

    def create_page(self, parent_id: str, properties: dict,
                    children: list | None = None,
                    parent_type: str = "database_id") -> dict:
        """创建页面（在数据库或页面下）"""
        payload: dict[str, Any] = {
            "parent": {"type": parent_type, parent_type: parent_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children
        return self._post("/pages", payload)

    def update_page(self, page_id: str, properties: dict) -> dict:
        """更新页面属性"""
        return self._patch(f"/pages/{page_id}", {"properties": properties})

    def append_blocks(self, block_id: str, children: list) -> dict:
        """向页面/块追加内容"""
        return self._patch(f"/blocks/{block_id}/children", {"children": children})

    # ==================== 便捷方法 ====================

    def log_gitea_event(self, database_id: str, *,
                        title: str,
                        event_type: str,
                        repository: str,
                        author: str,
                        url: str,
                        summary: str,
                        branch: str = "",
                        status: str = "",
                        ) -> dict:
        """向 Gitea 事件数据库中写入一条记录"""
        properties = {
            "Name": {"title": [{"text": {"content": title}}]},
            "Type": {"select": {"name": event_type}},
            "Repository": {"rich_text": [{"text": {"content": repository}}]},
            "Author": {"rich_text": [{"text": {"content": author}}]},
            "URL": {"url": url},
            "Date": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        }
        if branch:
            properties["Branch"] = {"rich_text": [{"text": {"content": branch}}]}
        if status:
            properties["Status"] = {"select": {"name": status}}

        # 页面正文（详细描述）
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": summary}}]
                },
            },
            {
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": url},
            },
        ]

        return self.create_page(database_id, properties, children)

    def find_page_by_title(self, database_id: str, title: str) -> dict | None:
        """按标题查找数据库中的页面，返回第一个匹配"""
        result = self.query_database(database_id, filter_obj={
            "property": "Name",
            "title": {"equals": title},
        })
        pages = result.get("results", [])
        return pages[0] if pages else None

    def update_event_page(self, page_id: str, *,
                          status: str = "",
                          summary: str = "") -> dict:
        """更新事件页面的状态和追加摘要"""
        properties = {}
        if status:
            properties["Status"] = {"select": {"name": status}}
        result = {}
        if properties:
            result = self.update_page(page_id, properties)
        if summary:
            self.append_blocks(page_id, [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": summary}}]
                    },
                },
            ])
        return result

    # ==================== 内部 HTTP 方法 ====================

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = self._session.post(url, json=payload, timeout=15)
        return self._handle(resp)

    def _patch(self, path: str, payload: dict) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = self._session.patch(url, json=payload, timeout=15)
        return self._handle(resp)

    def _handle(self, resp: requests.Response) -> dict:
        if resp.status_code >= 400:
            logger.error("Notion API 错误 %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()
