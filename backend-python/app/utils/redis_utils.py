"""Redis 连接工具 —— 全局单例连接池。"""

import redis
from app.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """获取 Redis 客户端实例（懒加载，全局单例）。"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            decode_responses=True,
        )
    return _redis_client
