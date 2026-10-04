# -*- coding: utf-8 -*-
"""运行日志中枢：入库 + 增量读取（FR-4.2 / 4.7）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import RunLog


def log(session: Session, run_id: int, level: str, source: str, message: str) -> None:
    session.add(RunLog(run_id=run_id, level=level, source=source, message=message))
    session.commit()


def fetch_since(session: Session, run_id: int, since: int = 0, limit: int = 500) -> list[RunLog]:
    stmt = select(RunLog).where(RunLog.run_id == run_id, RunLog.id > since).order_by(RunLog.id).limit(limit)
    return list(session.scalars(stmt))


def to_item(row: RunLog) -> dict:
    return {
        "id": row.id,
        "level": row.level,
        "source": row.source,
        "message": row.message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def now() -> datetime:
    return datetime.now()
