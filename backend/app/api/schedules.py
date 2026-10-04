# -*- coding: utf-8 -*-
"""定时任务管理 API（FR-4.8, A15）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import Schedule, StorageTarget, User
from services import scheduler_service

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleIn(BaseModel):
    name: str
    kind: str  # minute / hour / day / week / daily / weekly
    n: int = 1
    time: str = "00:00"
    weekdays: list[int] = [1]
    mode: str
    params: dict = {}
    bind_target_ids: list[int] = []
    enable: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    n: int | None = None
    time: str | None = None
    weekdays: list[int] | None = None
    mode: str | None = None
    params: dict | None = None
    bind_target_ids: list[int] | None = None
    enable: bool | None = None


def _item(s: Schedule) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "cron": s.cron,
        "mode": s.mode,
        "params": s.params or {},
        "enable": s.enable,
        "disabled_reason": s.disabled_reason,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _translate(kind: str, n: int, time: str, weekdays: list[int]) -> str:
    try:
        return scheduler_service.to_cron(kind, n=n, time=time, weekdays=weekdays)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"定时参数无效: {exc}") from exc


def _check_binding(mode: str, target_ids: list[int], db: Session) -> list[int]:
    if mode == "crawl":
        return []
    targets = db.scalars(select(StorageTarget).where(StorageTarget.id.in_(target_ids))).all() if target_ids else []
    enabled = [t.id for t in targets if t.enable]
    if not enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "回测 / 爬取+聚合模式必须绑定至少一个已启用的存储目标"
        )
    return enabled


@router.get("")
def list_schedules(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(select(Schedule).order_by(Schedule.id)).all()
    return {"total": len(rows), "items": [_item(s) for s in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_schedule(
    body: ScheduleIn,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    if body.mode not in ("crawl", "aggregate", "full"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "运行模式须为 crawl / aggregate / full")
    cron = _translate(body.kind, body.n, body.time, body.weekdays)
    bound = _check_binding(body.mode, body.bind_target_ids, db)
    params = dict(body.params or {})
    params["spec"] = {"kind": body.kind, "n": body.n, "time": body.time, "weekdays": body.weekdays}
    if bound:
        params["bind_target_ids"] = bound
    schedule = Schedule(
        name=body.name,
        cron=cron,
        mode=body.mode,
        params=params,
        enable=body.enable,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    from engine_adapter.scheduler import SchedulerHub

    SchedulerHub.instance().resync()
    return _item(schedule)


@router.put("/{schedule_id}")
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "定时任务不存在")
    mode = body.mode or schedule.mode
    if body.kind is not None or body.n is not None or body.time is not None or body.weekdays is not None:
        spec = dict((schedule.params or {}).get("spec") or {})
        spec.update({
            "kind": body.kind or spec.get("kind") or "minute",
            "n": body.n if body.n is not None else spec.get("n", 1),
            "time": body.time or spec.get("time") or "00:00",
            "weekdays": body.weekdays or spec.get("weekdays") or [1],
        })
        schedule.cron = _translate(spec["kind"], spec["n"], spec["time"], spec["weekdays"])
        params["spec"] = spec
    if body.name is not None:
        schedule.name = body.name
    schedule.mode = mode
    if body.params is not None:
        params = dict(body.params)
    else:
        params = dict(schedule.params or {})
    bound = _check_binding(mode, body.bind_target_ids if body.bind_target_ids is not None else params.get("bind_target_ids", []), db)
    if bound:
        params["bind_target_ids"] = bound
    schedule.params = params
    if body.enable is not None:
        schedule.enable = body.enable
        if body.enable:
            schedule.disabled_reason = None
    db.commit()
    db.refresh(schedule)
    from engine_adapter.scheduler import SchedulerHub

    SchedulerHub.instance().resync()
    return _item(schedule)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "定时任务不存在")
    db.delete(schedule)
    db.commit()
    from engine_adapter.scheduler import SchedulerHub

    SchedulerHub.instance().resync()
    return {"ok": True}


@router.post("/{schedule_id}/toggle")
def toggle_schedule(
    schedule_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "定时任务不存在")
    schedule.enable = not schedule.enable
    if schedule.enable:
        schedule.disabled_reason = None
    db.commit()
    db.refresh(schedule)
    from engine_adapter.scheduler import SchedulerHub

    SchedulerHub.instance().resync()
    return _item(schedule)
