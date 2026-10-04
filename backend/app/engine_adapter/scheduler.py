# -*- coding: utf-8 -*-
"""定时调度执行器：APScheduler 到点为启用 schedule 生成 run（FR-4.8 / A15）。"""

from __future__ import annotations

import threading
from datetime import datetime

import db
from models import CrawlRun, Schedule
from sqlalchemy import select
from sqlalchemy.orm import Session

TERMINAL = ("success", "failed", "cancelled", "partial-success")


class SchedulerHub:
    """每个 schedule 一个 cron job；到点触发 TaskRunner 创建 run。

    - 执行器被占用：跳过本轮，disabled_reason 记录原因（下轮恢复时清除）
    - schedule 变更后调用 resync() 重建作业
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduler = None

    _instance: "SchedulerHub | None" = None
    _singleton_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "SchedulerHub":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---------- 生命周期 ----------
    def start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        with self._lock:
            if self._scheduler is not None:
                return
            self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
            self._scheduler.start()
        self.resync()

    def stop(self) -> None:
        with self._lock:
            if self._scheduler is not None:
                self._scheduler.shutdown(wait=False)
                self._scheduler = None

    # ---------- 作业同步 ----------
    def resync(self, session: Session | None = None) -> None:
        """按 DB 中启用 schedule 重建作业（创建/更新/删除后调用）。"""
        own = session is None
        session = session or db.SessionLocal()
        try:
            schedules = session.scalars(select(Schedule)).all()
            with self._lock:
                scheduler = self._scheduler
                if scheduler is None:
                    return
                wanted = {f"schedule-{s.id}" for s in schedules if s.enable}
                for job in scheduler.get_jobs():
                    if job.id not in wanted:
                        scheduler.remove_job(job.id)
                for item in schedules:
                    if not item.enable:
                        continue
                    self._add_job(scheduler, item)
        finally:
            if own:
                session.close()

    def _add_job(self, scheduler, item: Schedule) -> None:
        from apscheduler.triggers.cron import CronTrigger

        job_id = f"schedule-{item.id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        trigger = CronTrigger.from_crontab(item.cron, timezone="Asia/Shanghai")
        scheduler.add_job(self._on_trigger, trigger=trigger, args=[item.id], id=job_id, replace_existing=True)

    # ---------- 触发 ----------
    def _on_trigger(self, schedule_id: int) -> None:
        session = db.SessionLocal()
        try:
            self.fire(schedule_id, session=session)
        finally:
            session.close()

    def fire(self, schedule_id: int, session: Session | None = None) -> CrawlRun | None:
        """到点触发：生成 trigger=schedule 的 run 并提交执行器；忙碌/停用时返回 None。"""
        from engine_adapter.runner import TaskRunner

        own = session is None
        session = session or db.SessionLocal()
        try:
            schedule = session.get(Schedule, schedule_id)
            if schedule is None or not schedule.enable:
                return None

            runner = TaskRunner.instance()
            with runner._lock:
                busy = runner.running_id is not None
            if busy:
                schedule.disabled_reason = "上轮任务仍在运行，本轮跳过"
                session.commit()
                return None

            params = dict(schedule.params or {})
            run = runner.create(
                session,
                mode=schedule.mode,
                params=params,
                source_ids=list(params.get("source_ids") or []),
                bind_target_ids=list(params.get("bind_target_ids") or []),
                actor_id=None,
                trigger="schedule",
            )
            schedule.last_run_at = datetime.now()
            if schedule.disabled_reason:
                schedule.disabled_reason = None  # 恢复
            session.commit()
            runner.start(run.id)
            return run
        finally:
            if own:
                session.close()

    def schedule(self, schedule_id: int) -> Schedule | None:
        session = db.SessionLocal()
        try:
            return session.get(Schedule, schedule_id)
        finally:
            session.close()
