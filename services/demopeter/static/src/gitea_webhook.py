"""
Gitea Webhook 处理器 — 接收 Gitea 事件并同步到 Notion
支持事件: push / issues / pull_request / release
"""
import hashlib
import hmac
import json
import logging
from typing import Any

from flask import Request

from config.settings import config
from src.notion_client import NotionClient

logger = logging.getLogger(__name__)


class GiteaWebhookHandler:
    """解析 Gitea webhook 并同步到 Notion"""

    # Gitea 事件 → Notion 事件类型
    EVENT_MAP = {
        "push":          "Commit",
        "issues":        "Issue",
        "pull_request":  "Pull Request",
        "release":       "Release",
    }

    def __init__(self):
        self._notion: NotionClient | None = None

    @property
    def notion(self) -> NotionClient:
        if self._notion is None:
            self._notion = NotionClient()
        return self._notion

    # ==================== 签名验证 ====================

    @staticmethod
    def verify_signature(request: Request) -> bool:
        """验证 Gitea webhook 签名 (HMAC-SHA256)"""
        secret = config.GITEA_WEBHOOK_SECRET
        if not secret:
            # 未配置 secret 则跳过验证
            return True

        signature = request.headers.get("X-Gitea-Signature", "")
        if not signature:
            logger.warning("缺少 X-Gitea-Signature 头")
            return False

        body = request.get_data()
        expected = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    # ==================== 事件分发 ====================

    def handle(self, request: Request) -> dict:
        """解析请求并分发到对应处理器"""
        event_type = request.headers.get("X-Gitea-Event", "")
        payload = request.get_json() or {}

        if event_type not in self.EVENT_MAP:
            return {"status": "ignored", "event": event_type}

        handler = getattr(self, f"handle_{event_type}", None)
        if handler is None:
            return {"status": "unsupported", "event": event_type}

        try:
            result = handler(payload)
            return {"status": "ok", "event": event_type, **result}
        except Exception as e:
            logger.exception("处理 %s 事件失败", event_type)
            return {"status": "error", "event": event_type, "error": str(e)}

    # ==================== Push 事件 ====================

    def handle_push(self, payload: dict) -> dict[str, Any]:
        """处理代码推送事件"""
        repo = payload.get("repository", {})
        repo_full = repo.get("full_name", "")
        pusher = payload.get("pusher", {})
        author = pusher.get("full_name") or pusher.get("login", "unknown")
        ref = payload.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

        commits = payload.get("commits", [])
        if not commits:
            return {"action": "push_no_commits", "branch": branch}

        # 汇总提交信息
        commit_list = []
        for c in commits[:10]:  # 最多10条
            msg = c.get("message", "").split("\n")[0][:80]
            commit_list.append(f"• `{c.get('id', '')[:8]}` {msg} - {c.get('author', {}).get('name', '')}")

        summary = f"**{len(commits)} 个提交** 推送到 `{branch}`\n\n" + "\n".join(commit_list)
        title = f"[Push] {repo_full} → {branch} ({len(commits)} commits)"

        page = self.notion.log_gitea_event(
            database_id=config.NOTION_DATABASE_ID,
            title=title,
            event_type="Commit",
            repository=repo_full,
            author=author,
            url=payload.get("compare_url", repo.get("html_url", "")),
            summary=summary,
            branch=branch,
        )
        return {"action": "push", "branch": branch, "commits": len(commits),
                "notion_page_id": page.get("id")}

    # ==================== Issues 事件 ====================

    def handle_issues(self, payload: dict) -> dict[str, Any]:
        """处理 Issue 事件（创建/更新/关闭）"""
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        repo = payload.get("repository", {})
        repo_full = repo.get("full_name", "")
        sender = payload.get("sender", {})
        author = sender.get("full_name") or sender.get("login", "unknown")
        issue_title = issue.get("title", "")
        issue_url = issue.get("html_url", "")
        issue_number = issue.get("number", "")
        state = issue.get("state", "open")

        title = f"[Issue #{issue_number}] {issue_title}"

        if action == "opened":
            summary = (
                f"**{author}** 创建了 Issue #{issue_number}\n\n"
                f"{issue.get('body', '')[:1500]}"
            )
            page = self.notion.log_gitea_event(
                database_id=config.NOTION_DATABASE_ID,
                title=title,
                event_type="Issue",
                repository=repo_full,
                author=author,
                url=issue_url,
                summary=summary,
                status=state.capitalize(),
            )
            return {"action": "issue_opened", "issue": issue_number,
                    "notion_page_id": page.get("id")}

        elif action == "closed":
            # 查找已有页面并更新状态
            existing = self.notion.find_page_by_title(
                config.NOTION_DATABASE_ID, title)
            if existing:
                self.notion.update_event_page(
                    existing["id"],
                    status="Closed",
                    summary=f"**{author}** 关闭了此 Issue",
                )
                return {"action": "issue_closed", "issue": issue_number, "updated": True}
            return {"action": "issue_closed", "issue": issue_number, "updated": False}

        else:
            # reopened / edited / assigned 等
            existing = self.notion.find_page_by_title(
                config.NOTION_DATABASE_ID, title)
            if existing:
                self.notion.append_blocks(existing["id"], [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": f"事件: {action} by {author}"}
                            }]
                        },
                    },
                ])
                return {"action": f"issue_{action}", "issue": issue_number, "updated": True}
            return {"action": f"issue_{action}", "issue": issue_number, "updated": False}

    # ==================== Pull Request 事件 ====================

    def handle_pull_request(self, payload: dict) -> dict[str, Any]:
        """处理 PR 事件"""
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        repo_full = repo.get("full_name", "")
        sender = payload.get("sender", {})
        author = sender.get("full_name") or sender.get("login", "unknown")
        pr_title = pr.get("title", "")
        pr_url = pr.get("html_url", "")
        pr_number = pr.get("number", "")
        from_branch = pr.get("head", {}).get("label", "")
        to_branch = pr.get("base", {}).get("label", "")
        state = pr.get("state", "open")
        merged = pr.get("merged", False)

        title = f"[PR #{pr_number}] {pr_title}"
        status = "Merged" if merged else state.capitalize()

        if action == "opened":
            summary = (
                f"**{author}** 创建了 Pull Request\n"
                f"`{from_branch}` → `{to_branch}`\n\n"
                f"{pr.get('body', '')[:1500]}"
            )
            page = self.notion.log_gitea_event(
                database_id=config.NOTION_DATABASE_ID,
                title=title,
                event_type="Pull Request",
                repository=repo_full,
                author=author,
                url=pr_url,
                summary=summary,
                status=status,
            )
            return {"action": "pr_opened", "pr": pr_number,
                    "notion_page_id": page.get("id")}

        elif action == "closed":
            existing = self.notion.find_page_by_title(
                config.NOTION_DATABASE_ID, title)
            if existing:
                merge_msg = "已合并" if merged else "已关闭（未合并）"
                self.notion.update_event_page(
                    existing["id"],
                    status="Merged" if merged else "Closed",
                    summary=f"**{author}** {merge_msg}",
                )
                return {"action": "pr_closed", "pr": pr_number,
                        "merged": merged, "updated": True}
            return {"action": "pr_closed", "pr": pr_number, "updated": False}

        else:
            return {"action": f"pr_{action}", "pr": pr_number}

    # ==================== Release 事件 ====================

    def handle_release(self, payload: dict) -> dict[str, Any]:
        """处理 Release 事件"""
        action = payload.get("action", "")
        release = payload.get("release", {})
        repo = payload.get("repository", {})
        repo_full = repo.get("full_name", "")
        sender = payload.get("sender", {})
        author = sender.get("full_name") or sender.get("login", "unknown")
        tag = release.get("tag_name", "")
        release_name = release.get("name", "") or tag
        release_url = release.get("html_url", "")
        body_text = release.get("body", "") or ""

        title = f"[Release] {repo_full} {tag}"

        if action == "published":
            summary = (
                f"**{release_name}** 已发布\n\n"
                f"{body_text[:1500]}"
            )
            page = self.notion.log_gitea_event(
                database_id=config.NOTION_DATABASE_ID,
                title=title,
                event_type="Release",
                repository=repo_full,
                author=author,
                url=release_url,
                summary=summary,
                status="Published",
            )
            return {"action": "release_published", "tag": tag,
                    "notion_page_id": page.get("id")}

        return {"action": f"release_{action}", "tag": tag}
