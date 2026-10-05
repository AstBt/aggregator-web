# -*- coding: utf-8 -*-
"""认证 API：登录/登出/me/改密（FR-1.1~1.8）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from settings import settings
from db import get_db
from deps import get_current_user
from models import User
from ratelimit import login_limiter
from schemas import LoginParams, LoginResult, PasswordChange, UserInfo
from security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResult)
def login(params: LoginParams, request: Request, db: Session = Depends(get_db)) -> LoginResult:
    ip = _client_ip(request)
    if not login_limiter.allow(f"ip:{ip}") or not login_limiter.allow(f"user:{params.username}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "尝试过于频繁，请稍后再试")

    user = db.query(User).filter_by(username=params.username).first()
    now = datetime.now()
    if user is not None and user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_423_LOCKED, "账号已锁定，请 15 分钟后再试")
    if user is None or not user.enable or not verify_password(params.password, user.password_hash):
        if user is not None:
            user.failed_count += 1
            if user.failed_count >= settings.login_max_fails:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_count = 0
            db.commit()
        # 不区分"用户不存在/密码错误/已禁用"，防账号枚举
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")

    user.failed_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return LoginResult(accessToken=create_token(user.id, user.token_version))


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    user.token_version += 1  # 服务端令牌失效
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserInfo)
def me(user: User = Depends(get_current_user)) -> UserInfo:
    return UserInfo.model_validate(user)


@router.put("/password")
def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码错误")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # 其他会话全部失效
    db.commit()
    return {"ok": True}
