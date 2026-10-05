# -*- coding: utf-8 -*-
"""安全：密码哈希（SHA256→bcrypt）、JWT、角色。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt

from settings import settings

Role = Literal["admin", "operator", "viewer"]
ROLES: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


def _digest(plain: str) -> bytes:
    # bcrypt 仅使用前 72 字节，先 SHA-256 规避截断（NFR-1）
    return hashlib.sha256(plain.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_digest(plain), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_digest(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: int, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def role_at_least(actual: str, required: str) -> bool:
    return ROLES.get(actual, -1) >= ROLES.get(required, 99)
