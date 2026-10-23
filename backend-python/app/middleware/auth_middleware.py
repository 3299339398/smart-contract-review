from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.jwt_utils import decode_token, get_token_hash
from app.utils.redis_utils import get_redis

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> int:
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    claims = decode_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # 检查 Redis 黑名单
    redis = get_redis()
    token_hash = get_token_hash(token)
    if redis.exists(f"scr:auth:blacklist:{token_hash}"):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    return int(claims["sub"])


async def get_optional_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> int | None:
    try:
        return await get_current_user_id(request, credentials)
    except HTTPException:
        return None
