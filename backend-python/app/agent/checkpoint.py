"""LangGraph 原生 checkpoint 持久化。

进程内复用一个 AsyncSqliteSaver 连接；checkpoint 数据保存在可持久化目录
中，任务线程 ID 由用户和任务共同限定，避免不同用户之间复用图状态。
"""

import asyncio
from pathlib import Path

from app.config import settings


_saver = None
_saver_lock = asyncio.Lock()


async def get_checkpoint_saver():
    """获取进程级 LangGraph 原生异步 SQLite saver。"""
    global _saver
    if _saver is not None:
        return _saver

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    import aiosqlite

    path = Path(settings.langgraph_checkpoint_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.parent.mkdir(parents=True, exist_ok=True)

    async with _saver_lock:
        if _saver is None:
            conn = await aiosqlite.connect(str(path))
            saver = AsyncSqliteSaver(conn)
            try:
                await saver.setup()
            except BaseException:
                await conn.close()
                raise
            _saver = saver
    return _saver


def checkpoint_config(task_id: int | str, user_id: int) -> dict:
    """返回所有图执行都必须使用的线程配置。"""
    return {
        "configurable": {
            "thread_id": f"review:{user_id}:{task_id}",
        },
    }


async def close_checkpoint_saver() -> None:
    """关闭应用退出时的 SQLite 连接。"""
    global _saver
    async with _saver_lock:
        if _saver is not None:
            await _saver.conn.close()
            _saver = None
