"""结构化日志配置。

为 opscli 各模块提供统一的日志初始化接口，
替代零散的 print() 调用，便于生产环境统一采集和过滤。
"""
from __future__ import annotations

import logging
import sys


def get_logger(name: str = "opscli") -> logging.Logger:
    """获取 opscli 命名空间下的 Logger 实例。

    首次调用时自动配置 stderr handler 和统一格式，
    后续调用直接返回已配置的 Logger。

    Args:
        name: Logger 名称，默认 "opscli"；模块级可传入 "opscli.auth" 等

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
    return logger