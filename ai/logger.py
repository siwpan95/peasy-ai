"""
日志系统：统一日志管理，替换所有 print()。
支持文件轮转、级别控制、结构化输出。
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# 包级日志
logger = logging.getLogger("easy_ai")

# 日志格式
_CONSOLE_FMT = "\033[36m%(asctime)s\033[0m \033[32m%(levelname)-8s\033[0m \033[33m%(name)s\033[0m - %(message)s"
_FILE_FMT = "%(asctime)s %(levelname)-8s %(name)s [%(filename)s:%(lineno)d] - %(message)s"

# Windows 下不支持 ANSI 转义，使用纯文本格式
if os.name == "nt":
    _CONSOLE_FMT = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
else:
    _CONSOLE_FMT = _CONSOLE_FMT


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 3,
    verbose: bool = False,
) -> logging.Logger:
    """
    初始化日志系统。

    Args:
        level: 日志级别（logging.DEBUG / INFO / WARNING / ERROR）。
        log_file: 日志文件路径。为 None 时不写文件。
        max_bytes: 单文件最大字节数，超过则轮转。
        backup_count: 保留的旧日志文件数量。
        verbose: 是否同时输出 DEBUG 到控制台。

    Returns:
        配置好的包级 logger。
    """
    root = logging.getLogger("easy_ai")
    root.setLevel(logging.DEBUG if verbose else level)

    # 避免重复添加 handler
    if root.handlers:
        return root

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else level)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    # 文件 handler（可选）
    if log_file:
        try:
            from logging.handlers import RotatingFileHandler
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)  # 文件始终记录 DEBUG
            fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt="%Y-%m-%d %H:%M:%S"))
            root.addHandler(fh)
        except Exception as e:
            root.warning("无法创建日志文件 %s: %s", log_file, e)

    root.info("日志系统初始化完成（级别=%s）", logging.getLevelName(level))
    return root


def get_logger(name: str) -> logging.Logger:
    """获取子模块 logger。"""
    return logging.getLogger(f"easy_ai.{name}")


# 便捷函数：懒初始化
_root_logger: Optional[logging.Logger] = None


def ensure_logger() -> logging.Logger:
    """确保日志系统已初始化（懒加载）。"""
    global _root_logger
    if _root_logger is None:
        _root_logger = setup_logging()
    return _root_logger


# 默认初始化（可被用户覆盖）
ensure_logger()
