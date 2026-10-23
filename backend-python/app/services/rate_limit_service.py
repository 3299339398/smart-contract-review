import time
from app.utils.redis_utils import get_redis

RATE_LIMIT_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local fields = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(fields[1])
local last_refill = tonumber(fields[2])

if tokens == nil or last_refill == nil then
    tokens = capacity - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 2 * window)
    return {1, tokens, now + window * 1000}
end

local elapsed = (now - last_refill) / 1000
local refill_rate = capacity / window
local refill = math.floor(elapsed * refill_rate)
tokens = math.min(capacity, tokens + refill)

if tokens > 0 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 2 * window)
    return {1, tokens, now + window * 1000}
else
    return {0, 0, last_refill + window * 1000}
end
"""


def rate_limit(user_id: int, endpoint: str, max_requests: int = 10,
               window_seconds: int = 60) -> bool:
    redis = get_redis()
    key = f"scr:ratelimit:{user_id}:{endpoint}"
    now_ms = int(time.time() * 1000)
    result = redis.eval(RATE_LIMIT_LUA, 1, key, max_requests, window_seconds, now_ms)
    allowed = int(result[0])
    if not allowed:
        raise RateLimitExceededException(
            f"请求太频繁，请稍后重试。限制: {max_requests}次/{window_seconds}秒"
        )
    return True


class RateLimitExceededException(Exception):
    pass
