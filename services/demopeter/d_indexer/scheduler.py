"""
DScheduler - D 盘每日自动扫描调度器

在 Flask 后台线程中运行，每天定时触发增量扫描。
也支持手动触发。

断点续传：
- 启动时自动检测未完成的扫描并续传
- 定时扫描默认使用增量模式（增量也受益于文件缓存加速）
"""
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from config.logging_config import get_logger

logger = get_logger("d_scheduler")


class DScheduler:
    """每日扫描调度器（支持断点续传）"""

    def __init__(self, indexer, scan_hour: int = 3, scan_minute: int = 0):
        """
        Args:
            indexer: DIndexer 实例
            scan_hour: 每天几点扫描 (默认凌晨 3 点)
            scan_minute: 分钟
        """
        self.indexer = indexer
        self.scan_hour = scan_hour
        self.scan_minute = scan_minute
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_scan: Optional[datetime] = None
        self._last_result = None
        self._on_scan_complete: Optional[Callable] = None
        self._resume_on_start = True  # 启动时是否续传中断的扫描

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def last_scan_time(self) -> Optional[str]:
        return self._last_scan.isoformat() if self._last_scan else None

    @property
    def last_result(self):
        return self._last_result

    def start(self, on_complete: Callable = None, resume: bool = True):
        """启动后台调度线程
        
        Args:
            on_complete: 扫描完成回调
            resume: 是否在启动时检测并续传中断的扫描
        """
        if self._running:
            return

        self._on_scan_complete = on_complete
        self._resume_on_start = resume
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        # 启动时的续传提示
        if resume and self.indexer.checkpoint.has_incomplete():
            logger.info("检测到未完成的扫描，首次扫描将自动续传")

        logger.info("已启动, 每天 %02d:%02d 自动扫描", self.scan_hour, self.scan_minute)

    def stop(self):
        """停止调度"""
        self._stop_event.set()
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("已停止")

    def trigger_now(self) -> dict:
        """立即手动触发一次增量扫描"""
        return self._do_scan("manual")

    def trigger_full(self) -> dict:
        """立即手动触发一次全量扫描（从零开始，重置断点）"""
        logger.info("手动触发全量扫描（将重置所有断点）...")
        self.indexer.checkpoint.reset_all()
        return self._do_scan("manual_full", force_full=True)

    def trigger_resume(self) -> dict:
        """手动触发断点续传"""
        return self._do_scan("manual_resume", force_full=True)

    def get_checkpoint_status(self) -> list:
        """获取所有项目的断点状态"""
        return self.indexer.checkpoint.get_all_progress()

    def _run_loop(self):
        """调度主循环"""
        # 启动时：如果有未完成的扫描，立即执行续传
        if self._resume_on_start and self.indexer.checkpoint.has_incomplete():
            logger.info("启动时检测到未完成的扫描，立即开始续传...")
            time.sleep(2)  # 等 Flask 完全启动
            self._do_scan("resume_on_start")

        while not self._stop_event.is_set():
            now = datetime.now()
            next_scan = now.replace(
                hour=self.scan_hour,
                minute=self.scan_minute,
                second=0,
                microsecond=0,
            )
            if next_scan <= now:
                next_scan += timedelta(days=1)

            wait_seconds = (next_scan - now).total_seconds()
            logger.info("下次扫描: %s (等待 %.1f 小时)",
                       next_scan.strftime("%Y-%m-%d %H:%M"), wait_seconds / 3600)

            # 分段等待，方便响应 stop
            while wait_seconds > 0 and not self._stop_event.is_set():
                sleep_time = min(wait_seconds, 60)
                time.sleep(sleep_time)
                wait_seconds -= sleep_time

            if not self._stop_event.is_set():
                self._do_scan("scheduled")

    def _do_scan(self, trigger: str, force_full: bool = False) -> dict:
        """执行扫描"""
        logger.info("开始 %s 扫描...", trigger)
        start = time.time()

        try:
            if force_full:
                # 全量扫描（已重置断点）
                result = self.indexer.index_with_resume(resume=True)
            elif self.indexer.count == 0:
                # 首次或索引为空 → 断点续传式全量
                result = self.indexer.index_with_resume(resume=True)
            else:
                # 增量扫描
                result = self.indexer.incremental_scan()

            self._last_scan = datetime.now()
            self._last_result = result

            duration = time.time() - start
            logger.info("%s 扫描完成: %d 文件 %d 新chunk 耗时 %.1fs",
                       trigger, result.total_files, result.new_chunks, duration)

            if self._on_scan_complete:
                self._on_scan_complete(result)

            return {
                "trigger": trigger,
                "total_files": result.total_files,
                "new_chunks": result.new_chunks,
                "skipped_chunks": result.skipped_chunks,
                "skipped_files": result.skipped_files,
                "duration_seconds": round(duration, 2),
                "timestamp": self.last_scan_time,
            }
        except Exception as e:
            logger.error("%s 扫描失败: %s", trigger, e)
            return {"trigger": trigger, "error": str(e)}
