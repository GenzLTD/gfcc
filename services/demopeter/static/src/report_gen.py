"""
szpeter2026 - 报告生成器
吸收自 Wukong report_gen.py，生成日/周/月报
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import config
from src.db_manager import DBManager


class ReportGenerator:
    """报告生成器 — 日报/周报/月报"""

    def __init__(self):
        self.db = DBManager()
        self.reports_dir = config.PROJECT_ROOT / "reports"
        self.reports_dir.mkdir(exist_ok=True)

    def generate_daily(self) -> str:
        """生成日报"""
        today = datetime.now().strftime("%Y-%m-%d")
        stats = self.db.get_stats()
        recent = self.db.get_recent_queries(limit=10)

        report = f"""# 📊 szpeter2026 日报 — {today}

## 知识库概况
| 指标 | 数值 |
|------|------|
| 文档总数 | {stats['documents_total']} |
| 已处理 | {stats['documents_completed']} |
| 分块总数 | {stats['chunks_total']} |
| 总字符数 | {stats['total_characters']:,} |
| 查询总数 | {stats['queries_total']} |

## 今日查询
{self._format_queries(recent)}

---
*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        path = self.reports_dir / f"daily_{today}.md"
        path.write_text(report, encoding="utf-8")
        return str(path)

    def generate_weekly(self) -> str:
        """生成周报"""
        week = datetime.now().strftime("%Y-W%W")
        report = f"""# 📈 szpeter2026 周报 — {week}

## 知识库统计
{self._format_stats_table()}

## 本周新增
- 文档：待补充
- 查询：待统计

---
*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        path = self.reports_dir / f"weekly_{week}.md"
        path.write_text(report, encoding="utf-8")
        return str(path)

    def generate_monthly(self) -> str:
        """生成月报"""
        month = datetime.now().strftime("%Y-%m")
        report = f"""# 📅 szpeter2026 月报 — {month}

## 知识库统计总览
{self._format_stats_table()}

## 月度总结
- 知识库持续增长中

---
*自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        path = self.reports_dir / f"monthly_{month}.md"
        path.write_text(report, encoding="utf-8")
        return str(path)

    def _format_stats_table(self) -> str:
        stats = self.db.get_stats()
        return f"""| 指标 | 数值 |
|------|------|
| 文档总数 | {stats['documents_total']} |
| 已处理文档 | {stats['documents_completed']} |
| 待处理文档 | {stats['documents_pending']} |
| 分块总数 | {stats['chunks_total']} |
| 总字符数 | {stats['total_characters']:,} |
| 历史查询 | {stats['queries_total']} |"""

    @staticmethod
    def _format_queries(queries: list[dict]) -> str:
        if not queries:
            return "暂无查询记录"
        return "\n".join(
            f"- [{q.get('created_at', '')[:16]}] {q['query_text'][:80]} ({q['provider']}, {q.get('response_time_ms', 0):.0f}ms)"
            for q in queries[:10]
        )
