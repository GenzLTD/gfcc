"""
DemoPeter 统一日志系统

替换散落的 print()，支持：
- 文件轮转（按天，保留 30 天）
- 控制台输出（开发模式）
- 级别过滤（DEBUG/INFO/WARNING/ERROR）
"""
import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

_INITIALIZED = False


def setup_logging(
    log_dir: str | Path = None,
    level: str = "INFO",
    console: bool = True,
) -> logging.Logger:
    """初始化统一日志系统

    Args:
        log_dir: 日志目录，默认 PROJECT_ROOT/logs/
        level: 日志级别
        console: 是否输出到控制台

    Returns:
        配置好的 root logger
    """
    global _INITIALIZED

    root_logger = logging.getLogger("demopeter")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清空已有 handler 后重新配置（解决模块导入时预装的 StreamHandler 阻塞问题）
    if _INITIALIZED:
        return root_logger
    root_logger.handlers.clear()

    # 格式：时间 | 级别 | 模块:行号 | 消息
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler — 按天轮转
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            filename=str(log_path / "demopeter.log"),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)

    # 控制台 handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(fmt)
        root_logger.addHandler(console_handler)

    _INITIALIZED = True
    root_logger.info("日志系统初始化完成 (level=%s)", level)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger"""
    return logging.getLogger(f"demopeter.{name}")
