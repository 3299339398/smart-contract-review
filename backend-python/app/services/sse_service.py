import asyncio
import logging
import json
import datetime
from typing import Optional
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# 每个任务独立的队列: key="review-{task_id}" → list of asyncio.Queue
_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe(task_id: int) -> asyncio.Queue:
    key = f"review-{task_id}"
    queue: asyncio.Queue = asyncio.Queue()
    if key not in _subscribers:
        _subscribers[key] = []
    _subscribers[key].append(queue)
    # 发送连接成功事件
    _send_raw(key, _format_sse("CONNECTED", task_id, "连接已建立"))
    return queue


async def unsubscribe(key: str, queue: asyncio.Queue):
    if key in _subscribers and queue in _subscribers[key]:
        _subscribers[key].remove(queue)
        if not _subscribers[key]:
            del _subscribers[key]


def send_event(task_id: int, event_type: str, **extra) -> None:
    key = f"review-{task_id}"
    data = _format_sse(event_type, task_id, **extra)
    _send_raw(key, data)


def _format_sse(event_type: str, task_id: int, *args, **extra) -> str:
    event = {
        "eventType": event_type,
        "taskId": str(task_id),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        **extra,
    }
    # 如果 extra 包含 'message' 键则保留
    if args:
        event["message"] = args[0]
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _send_raw(key: str, data: str) -> None:
    if key not in _subscribers:
        return
    dead = []
    for q in _subscribers[key]:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers[key].remove(q)


def complete_task(task_id: int) -> None:
    key = f"review-{task_id}"
    if key in _subscribers:
        for q in _subscribers[key]:
            try:
                q.put_nowait(None)  # 哨兵值，关闭流
            except Exception:
                pass
        del _subscribers[key]


async def create_sse_stream(task_id: int, token: str = None):
    """为指定任务创建 SSE StreamingResponse 流式响应。"""
    queue = subscribe(task_id)
    key = f"review-{task_id}"

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if data is None:  # 哨兵值
                        break
                    yield data
                except asyncio.TimeoutError:
                    yield ":heartbeat\n\n"  # 15 秒心跳保活
        except asyncio.CancelledError:
            pass
        finally:
            await unsubscribe(key, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
