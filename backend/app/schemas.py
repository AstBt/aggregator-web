# -*- coding: utf-8 -*-
"""Pydantic 数据契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from security import Role


# ---------- 认证 ----------
class LoginParams(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResult(BaseModel):
    accessToken: str


class UserInfo(BaseModel):
    id: int
    username: str
    role: Role
    enable: bool

    model_config = {"from_attributes": True}


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


# ---------- 用户管理 ----------
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=256)
    role: Role = "viewer"
    enable: bool = True


class UserUpdate(BaseModel):
    role: Role | None = None
    enable: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class UserListItem(BaseModel):
    id: int
    username: str
    role: Role
    enable: bool
    last_login_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class Page(BaseModel):
    total: int
    items: list
