"""报告生成辅助脚本 — 由 manage.ps1 Invoke-Report 调用"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bootstrap_paths  # noqa: F401
from src.report_gen import ReportGenerator

report_type = sys.argv[1] if len(sys.argv) > 1 else "daily"
r = ReportGenerator()
method = getattr(r, f"generate_{report_type}")
print(method())
