# -*- coding: utf-8 -*-
"""存储目标管理 API（FR-5.10~5.17, A14；v2.4：管理权限仅 admin）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import Schedule, StorageTarget, User
from services import storage_service

router = APIRouter(prefix="/api/storage-targets", tags=["storage"])


class TargetCreate(BaseModel):
    type: str
    name: str
    config: dict = {}
    token: str = ""


class TargetUpdate(BaseModel):
    config: dict | None = None
    token: str | None = None
    enable: bool | None = None


def _item(target: StorageTarget) -> dict:
    return {
        "id": target.id,
        "type": target.type,
        "type_name": storage_service.TYPES.get(target.type, {}).get("name", target.type),
        "name": target.name,
        "enable": target.enable,
        "config": target.config,
        "token_masked": storage_service.masked(target.token_ref or ""),
        "last_write_at": target.last_write_at.isoformat() if target.last_write_at else None,
        "last_write_ok": target.last_write_ok,
        "last_write_error": target.last_write_error,
    }


@router.get("")
def list_targets(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(select(StorageTarget).order_by(StorageTarget.id)).all()
    total = len(rows)
    return {"total": total, "items": [_item(t) for t in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_target(
    body: TargetCreate,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    errors = storage_service.validate_target(body.type, body.config, body.token)
    if errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "；".join(errors))
    if db.query(StorageTarget).filter_by(name=body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "目标名称已存在")
    target = StorageTarget(
        type=body.type,
        name=body.name,
        config=body.config,
        token_ref=storage_service.encrypt_token(body.token) if body.token else None,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return _item(target)


@router.put("/{target_id}")
def update_target(
    target_id: int,
    body: TargetUpdate,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(StorageTarget, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    if body.config is not None:
        target.config = body.config
    if body.token is not None:
        target.token_ref = storage_service.encrypt_token(body.token) if body.token else None
    if body.enable is not None:
        target.enable = body.enable
    db.commit()
    db.refresh(target)
    return _item(target)


@router.delete("/{target_id}")
def delete_target(
    target_id: int,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(StorageTarget, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    # NFR-12：引用该目标的 schedule 自动停用并标记原因
    for schedule in db.scalars(select(Schedule).where(Schedule.enable.is_(True))).all():
        bound = [t for t in (schedule.params or {}).get("bind_target_ids", []) if t == target_id]
        if bound:
            schedule.enable = False
            schedule.disabled_reason = f"绑定的存储目标 {target.name} 已被删除"
    db.delete(target)
    db.commit()
    return {"ok": True}


@router.post("/{target_id}/toggle")
def toggle_target(
    target_id: int,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(StorageTarget, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    target.enable = not target.enable
    db.commit()
    db.refresh(target)
    return _item(target)


@router.post("/{target_id}/test")
def test_target(
    target_id: int,
    _: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> dict:
    target = db.get(StorageTarget, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标不存在")
    token = storage_service.decrypt_token(target.token_ref or "")
    return storage_service.probe(target.type, dict(target.config or {}), token)
