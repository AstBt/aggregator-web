# -*- coding: utf-8 -*-
"""用户管理 API（FR-1.9~1.11）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import User
from schemas import Page, UserCreate, UserListItem, UserUpdate
from security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def _guard_last_admin(db: Session, user: User, role: str, enable: bool) -> None:
    """不允许禁用/降级/删除最后一个启用管理员（A2）。"""
    becoming_non_admin = role != "admin" or not enable
    if not becoming_non_admin:
        return
    active_admins = (
        db.query(func.count())
        .select_from(User)
        .where(User.role == "admin", User.enable.is_(True))
        .scalar()
    )
    if active_admins <= 1 and user.role == "admin" and user.enable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "系统至少需要保留一个启用的管理员")


@router.get("", response_model=Page)
def list_users(
    role: str | None = None,
    enable: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> Page:
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if enable is not None:
        stmt = stmt.where(User.enable == enable)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(total=total or 0, items=[UserListItem.model_validate(u) for u in items])


@router.post("", response_model=UserListItem, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> UserListItem:
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        enable=body.enable,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserListItem.model_validate(user)


@router.put("/{user_id}", response_model=UserListItem)
def update_user(
    user_id: int,
    body: UserUpdate,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> UserListItem:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    new_role = body.role if body.role is not None else user.role
    new_enable = body.enable if body.enable is not None else user.enable
    _guard_last_admin(db, user, new_role, new_enable)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    user.role = new_role
    user.enable = new_enable
    user.token_version += 1  # 角色/状态/密码变更即时生效（NFR-3）
    db.commit()
    db.refresh(user)
    return UserListItem.model_validate(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    _guard_last_admin(db, user, "viewer", False)
    db.delete(user)
    db.commit()
    return {"ok": True}
