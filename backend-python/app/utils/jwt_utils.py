"""JWT 工具模块 —— access token / refresh token 的签发与验证。"""

import hashlib
import uuid
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt
from app.config import settings


def _get_signing_key() -> str:
    """读取 JWT 签名密钥，并拒绝缺失或过短的部署配置。"""
    configured = (settings.jwt_secret or "").strip()
    if not configured:
        raise RuntimeError("JWT_SECRET must be configured")
    try:
        key = base64.b64decode(configured, validate=True)
    except Exception:
        key = configured.encode("utf-8")
    if len(key) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
    return key


def create_access_token(user_id: int, username: str, role: str) -> tuple[str, str, int]:
    """签发 access token，返回 (token, jti, expires_in_seconds)。"""
    now = datetime.utcnow()
    jti = str(uuid.uuid4())
    exp = now + timedelta(milliseconds=settings.jwt_expiration_ms)
    claims: Dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "type": "access",
        "jti": jti,
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(claims, _get_signing_key(), algorithm="HS256")
    expires_in = settings.jwt_expiration_ms // 1000
    return token, jti, expires_in


def create_refresh_token(user_id: int) -> tuple[str, str, int]:
    """签发 refresh token，有效期 7 天，返回 (token, jti, expires_in_seconds)。"""
    now = datetime.utcnow()
    jti = str(uuid.uuid4())
    exp = now + timedelta(days=7)
    claims: Dict[str, Any] = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(claims, _get_signing_key(), algorithm="HS256")
    expires_in = 7 * 86400
    return token, jti, expires_in


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """解码并验证 JWT token，失败返回 None。"""
    try:
        return jwt.decode(token, _get_signing_key(), algorithms=["HS256"])
    except Exception:
        return None


def get_token_hash(token: str) -> str:
    """对 token 做 SHA256 哈希，用于黑名单/缓存查找。"""
    return hashlib.sha256(token.encode()).hexdigest()
