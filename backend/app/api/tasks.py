# -*- coding: utf-8 -*-
"""任务 API：列表 / 详情 / 创建 / 取消 / 日志 / 重试发布 / 定时。"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from engine_adapter import log_hub
from engine_adapter.runner import TaskRunner
from models import Artifact, CrawlRun, StorageTarget, User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_started: set[int] = set()
_started_lock = threading.Lock()


class TaskCreate(BaseModel):
    mode: str
    params: dict = {}
    source_ids: list[int] = []
    bind_target_ids: list[int] = []
    schedule: dict | None = None  # {"kind": ..., "n": ..., "time": ..., "weekdays": [...]}


class RunItem(BaseModel):
    id: int
    run_uuid: str | None = None
    trigger: str
    mode: str
    status: str
    stage: str | None = None
    progress: dict | None = None
    stats: dict | None = None
    publish_pending: list | None = None
    params: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}


class RunDetail(RunItem):
    pass


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _to_item(run: CrawlRun) -> dict:
    return RunItem(
        id=run.id,
        run_uuid=run.run_uuid,
        trigger=run.trigger,
        mode=run.mode,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        stats=run.stats,
        publish_pending=run.publish_pending,
        params=run.params,
        error=run.error,
        started_at=_iso(run.started_at),
        finished_at=_iso(run.finished_at),
        duration_ms=run.duration_ms,
    ).model_dump()


@router.get("")
def list_tasks(
    status_: str | None = Query(None, alias="status"),
    mode: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(CrawlRun)
    if status_:
        stmt = stmt.where(CrawlRun.status == status_)
    if mode:
        stmt = stmt.where(CrawlRun.mode == mode)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    runs = db.scalars(stmt.order_by(CrawlRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [_to_item(r) for r in runs]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate,
    user: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    runner = TaskRunner.instance()
    with threading.Lock():
        if runner.running_id is not None:
            running = runner.running_id
        else:
            running = None
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"任务 #{running} 正在运行，请先等待或取消")

    if body.mode != "crawl":
        targets = db.scalars(select(StorageTarget).where(StorageTarget.id.in_(body.bind_target_ids))).all() if body.bind_target_ids else []
        enabled = [t for t in targets if t.enable]
        if not enabled:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "回测 / 爬取+聚合模式必须绑定至少一个已启用的存储目标")
        params = dict(body.params)
        params["bind_target_ids"] = [t.id for t in enabled]
    else:
        params = dict(body.params)
        params["bind_target_ids"] = []
    if body.source_ids:
        params["source_ids"] = body.source_ids

    try:
        run = runner.create(
            db,
            mode=body.mode,
            params=params,
            source_ids=list(params.get("source_ids") or []),
            bind_target_ids=list(params.get("bind_target_ids") or []),
            actor_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if body.schedule:
        from services import scheduler_service

        try:
            cron = scheduler_service.to_cron(
                body.schedule["kind"],
                n=int(body.schedule.get("n", 1)),
                time=str(body.schedule.get("time", "00:00")),
                weekdays=list(body.schedule.get("weekdays") or [1]),
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"定时参数无效: {exc}") from exc
        from models import Schedule

        db.add(
            Schedule(
                name=f"run-{run.id}",
                cron=cron,
                mode=body.mode,
                params=params,
                enable=True,
            )
        )
        db.commit()
        return _to_item(run)

    if not runner.start(run.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "任务启动失败：已有任务在运行")
    with _started_lock:
        _started.add(run.id)
    return _to_item(run)


@router.get("/{run_id}")
def task_detail(
    run_id: int,
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(CrawlRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return _to_item(run)


@router.get("/{run_id}/logs")
def task_logs(
    run_id: int,
    since: int = Query(0, ge=0),
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    rows = log_hub.fetch_since(db, run_id, since=since)
    return {"items": [log_hub.to_item(r) for r in rows]}


@router.post("/{run_id}/cancel")
def cancel_task(
    run_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(CrawlRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if run.status not in ("pending", "running"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅运行中的任务可取消")
    if not TaskRunner.instance().cancel(run_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "取消失败：任务未在运行")
    return {"ok": True}


@router.post("/{run_id}/retry-publish")
def retry_publish(
    run_id: int,
    _: User = Depends(require_role("operator")),
    db: Session = Depends(get_db),
) -> dict:
    from engine_adapter.publisher import retry_publish as _retry

    try:
        return _retry(db, run_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/{run_id}/artifacts")
def run_artifacts(
    run_id: int,
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(select(Artifact).where(Artifact.run_id == run_id)).all()
    return {
        "items": [
            {"id": a.id, "target": a.target, "path": a.path, "size": a.size, "created_at": _iso(a.created_at)}
            for a in rows
        ]
    }
