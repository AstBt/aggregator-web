# -*- coding: utf-8 -*-
"""FastAPI 依赖：当前用户、角色校验。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import User
from security import Role, decode_token, role_at_least

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "未认证或登录已过期") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthorized()
    payload = decode_token(credentials.credentials)
    if not payload:
        raise _unauthorized()
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.enable:
        raise _unauthorized()
    if payload.get("tv", -1) != user.token_version:
        raise _unauthorized("登录状态已失效，请重新登录")
    return user


def require_role(minimum: Role):
    """RBAC 服务端强校验（NFR-2）。"""

    def checker(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        if not role_at_least(user.role, minimum):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return checker
