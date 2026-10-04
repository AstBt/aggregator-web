# -*- coding: utf-8 -*-
"""仪表盘 API（FR-2.1~2.7, A3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from deps import require_role
from models import CrawlRun, CrawlSource, Node, StorageTarget, Subscription, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_DELAY_BUCKETS = (("<300ms", 0, 299), ("300-800ms", 300, 799), (">800ms", 800, None))


@router.get("/overview")
def overview(
    _: User = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "subs_total": db.scalar(select(func.count()).select_from(Subscription)) or 0,
        "subs_alive": db.scalar(
            select(func.count()).select_from(Subscription).where(Subscription.status == "alive")
        )
        or 0,
        "nodes_total": db.scalar(select(func.count()).select_from(Node)) or 0,
        "nodes_alive": db.scalar(select(func.count()).select_from(Node).where(Node.alive.is_(True))) or 0,
        "delay_buckets": [
            {"label": label, "count": _delay_count(db, low, high)} for label, low, high in _DELAY_BUCKETS
        ],
        "protocol_distribution": _group_count(db, Node.protocol, key_name="protocol"),
        "region_top": [
            {"region": region or "未知", "count": count}
            for region, count in db.execute(
                select(Node.region, func.count()).where(Node.alive.is_(True)).group_by(Node.region).order_by(func.count().desc()).limit(5)
            )
        ],
        "residential_count": db.scalar(
            select(func.count()).select_from(Node).where(Node.alive.is_(True), Node.residential.is_(True))
        )
        or 0,
        "avg_delay_ms": round(
            db.scalar(select(func.avg(Node.delay_ms)).where(Node.alive.is_(True), Node.delay_ms.isnot(None))) or 0
        ),
        "recent_runs": [
            _run_item(r)
            for r in db.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(10))
        ],
        "source_health": _source_health(db),
        "storage_targets_enabled": db.scalar(
            select(func.count()).select_from(StorageTarget).where(StorageTarget.enable.is_(True))
        )
        or 0,
        "storage_status": [
            {
                "name": t.name,
                "type": t.type,
                "enable": t.enable,
                "last_write_ok": t.last_write_ok,
                "last_write_at": t.last_write_at.isoformat() if t.last_write_at else None,
            }
            for t in db.scalars(select(StorageTarget).order_by(StorageTarget.id))
        ],
        "latest_run_id": db.scalar(select(func.max(Node.run_id))),
    }


def _delay_count(db: Session, low: int, high: int | None) -> int:
    stmt = select(func.count()).select_from(Node).where(Node.alive.is_(True), Node.delay_ms >= low)
    if high is not None:
        stmt = stmt.where(Node.delay_ms <= high)
    return db.scalar(stmt) or 0


def _group_count(db: Session, column, key_name: str = "key") -> list[dict]:
    return [
        {key_name: key, "count": count}
        for key, count in db.execute(select(column, func.count()).group_by(column))
    ]


def _source_health(db: Session) -> list[dict]:
    rows = db.execute(
        select(CrawlSource.type, func.count()).group_by(CrawlSource.type)
    ).all()
    enabled = {
        t: c
        for t, c in db.execute(
            select(CrawlSource.type, func.count()).where(CrawlSource.enable.is_(True)).group_by(CrawlSource.type)
        )
    }
    return [{"type": t, "total": total, "enabled": enabled.get(t, 0)} for t, total in rows]


def _run_item(run: CrawlRun) -> dict:
    return {
        "id": run.id,
        "mode": run.mode,
        "trigger": run.trigger,
        "status": run.status,
        "stage": run.stage,
        "duration_ms": run.duration_ms,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "stats": run.stats or {},
        "publish_pending": run.publish_pending or [],
    }
