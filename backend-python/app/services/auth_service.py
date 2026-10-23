import logging
from app.models import User
from app.utils.security import hash_password, verify_password
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_token, get_token_hash
from app.utils.redis_utils import get_redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class AuthService:

    @staticmethod
    async def register(db: AsyncSession, username: str, email: str, password: str) -> dict:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            raise ValueError("Email already registered")
        result = await db.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            raise ValueError("Username already taken")

        user = User(
            username=username,
            email=email,
            password=hash_password(password),
            role="USER",
            enabled=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return {"id": user.id, "username": user.username, "role": user.role}

    @staticmethod
    async def login(db: AsyncSession, email: str, password: str) -> dict:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password):
            raise ValueError("Invalid email or password")
        if not user.enabled:
            raise ValueError("User account is disabled")

        access_token, access_jti, access_expires = create_access_token(user.id, user.username, user.role)
        refresh_token, refresh_jti, _ = create_refresh_token(user.id)

        redis = get_redis()
        redis.setex(f"scr:auth:access:{user.id}", access_expires, access_token)
        redis.setex(f"scr:auth:refresh:{user.id}", 7 * 86400, refresh_token)

        return {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresIn": access_expires,
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @staticmethod
    async def refresh(refresh_token: str) -> dict:
        claims = decode_token(refresh_token)
        if not claims or claims.get("type") != "refresh":
            raise ValueError("Invalid refresh token")

        user_id = int(claims["sub"])
        redis = get_redis()
        stored = redis.get(f"scr:auth:refresh:{user_id}")
        if not stored or stored != refresh_token:
            raise ValueError("Refresh token has been rotated or revoked")

        from app.database import async_session_factory
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            if not user:
                raise ValueError("User not found")
            if not user.enabled:
                raise ValueError("User account is disabled")
            new_access, _, access_expires = create_access_token(user.id, user.username, user.role)
            new_refresh, _, _ = create_refresh_token(user.id)

        redis.setex(f"scr:auth:access:{user_id}", access_expires, new_access)
        redis.setex(f"scr:auth:refresh:{user_id}", 7 * 86400, new_refresh)

        return {
            "accessToken": new_access,
            "refreshToken": new_refresh,
            "expiresIn": access_expires,
            "user": {"id": user.id, "username": user.username, "role": user.role},
        }

    @staticmethod
    async def logout(access_token: str, refresh_token: str) -> None:
        redis = get_redis()
        claims = decode_token(access_token)
        if claims:
            token_hash = get_token_hash(access_token)
            import time
            ttl = max(1, int(claims.get("exp", time.time()) - time.time()))
            redis.setex(f"scr:auth:blacklist:{token_hash}", ttl, "1")
            redis.delete(f"scr:auth:access:{claims['sub']}")
        claims = decode_token(refresh_token) if refresh_token else None
        if claims:
            redis.delete(f"scr:auth:refresh:{claims['sub']}")
