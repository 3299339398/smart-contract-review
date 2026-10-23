"""日志工具 —— 统一的日志格式和级别配置。"""

import logging
from app.config import settings

def get_logger(name: str) -> logging.Logger:
    """获取配置好的 logger 实例，统一使用 ISO 时间戳格式。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    return logger
