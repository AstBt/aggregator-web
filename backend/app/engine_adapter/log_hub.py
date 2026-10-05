# -*- coding: utf-8 -*-
"""运行日志中枢：入库 + 增量读取 + 引擎日志捕获（FR-4.2 / 4.7）。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import RunLog


class RunLogHandler(logging.Handler):
    """把引擎/根 logger 的记录镜像进 run 日志（执行期间挂载）。"""

    def __init__(self, run_id: int) -> None:
        super().__init__(level=logging.INFO)
        self.run_id = run_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if "[Check]" in message and "finished" not in message:
                return  # 过滤单节点探测噪声
            log(
                self._session(),
                self.run_id,
                record.levelname,
                record.name,
                message,
            )
        except Exception:
            pass

    @staticmethod
    def _session() -> Session:
        import db

        return db.SessionLocal()


@contextmanager
def capture_engine_logs(run_id: int):
    """在执行期间将根 logger 记录镜像到 run 日志。"""
    handler = RunLogHandler(run_id)
    root = logging.getLogger()
    previous_level = root.level
    if previous_level > logging.INFO:
        root.setLevel(logging.INFO)  # 默认 root 为 WARNING，需放行 INFO
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


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
