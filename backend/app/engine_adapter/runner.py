# -*- coding: utf-8 -*-
"""任务执行器：全局单实例、阶段上报、取消安全点、引擎适配。"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

import db
from models import CrawlRun

try:
    from logger import logger  # noqa: F401
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("runner")


class RunCancelled(Exception):
    """任务在安全点被取消。"""


@dataclass
class RunContext:
    run_id: int
    mode: str  # crawl / aggregate / full
    params: dict
    source_ids: list[int]
    bind_target_ids: list[int]
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelled()


@dataclass
class LooseNode:
    """爬取直接获得的散节点（与订阅解析节点相互独立）。"""

    source: str  # 爬取源名称（TG 为频道名）
    uri: str = ""  # 原始分享链接
    proxy: dict | None = None  # 已解析的节点


@dataclass
class CrawlOutcome:
    subscriptions: list[tuple[str, str, bool]] = field(default_factory=list)  # (url, origin, reachable)
    loose: list[LooseNode] = field(default_factory=list)  # 散节点（带来源归属）


@dataclass
class EngineOutcome:
    subscriptions: list[tuple[str, str, bool]] = field(default_factory=list)  # (url, origin, reachable)
    loose: list["LooseNode"] = field(default_factory=list)  # 散节点（带来源归属）
    proxies: list[dict] = field(default_factory=list)  # 原始节点（含 _kind/_source/_source_sub 标记）
    alive: list[dict] = field(default_factory=list)  # 验活存活节点
    artifacts: list[dict] = field(default_factory=list)  # [{"target","path","size"}]


class Engine(Protocol):
    """引擎协议：抓取→拉取→验活→转换；真实实现见 engine.py。"""

    def crawl(self, ctx: RunContext) -> CrawlOutcome: ...

    def fetch(self, ctx: RunContext, subscriptions: list[str], loose: list[LooseNode]) -> list[dict]: ...

    def check(self, ctx: RunContext, proxies: list[dict]) -> list[dict]: ...

    def convert(self, ctx: RunContext, alive: list[dict]) -> list[dict]: ...


class HermeticEngine:
    """确定性测试/演示引擎：无网络、无二进制依赖。"""

    def __init__(self, subscriptions: list[tuple[str, str, bool]], proxies: list[dict]) -> None:
        self._subscriptions = subscriptions
        self._proxies = proxies

    def crawl(self, ctx: RunContext) -> CrawlOutcome:
        ctx.check_cancelled()
        return CrawlOutcome(subscriptions=list(self._subscriptions), loose=[])

    def fetch(self, ctx: RunContext, subscriptions: list[str], loose: list[LooseNode]) -> list[dict]:
        ctx.check_cancelled()
        return [{**p, "_kind": "sub"} for p in self._proxies]

    def check(self, ctx: RunContext, proxies: list[dict]) -> list[dict]:
        ctx.check_cancelled()
        return [dict(p) for p in proxies]

    def convert(self, ctx: RunContext, alive: list[dict]) -> list[dict]:
        ctx.check_cancelled()
        import os
        import tempfile

        targets = ("clash", "v2ray", "singbox")
        directory = tempfile.mkdtemp(prefix="agg-artifacts-")
        specs = []
        for target in targets:
            path = os.path.join(directory, f"{target}.txt")
            with open(path, "w", encoding="utf8") as f:
                f.write(f"# {target} export\n# nodes: {len(alive)}\n")
            specs.append({"target": target, "path": path, "size": os.path.getsize(path)})
        return specs


STAGES_CRAWL = ["init", "crawl", "done"]
STAGES_AGGREGATE = ["init", "fetch", "check", "convert", "publish", "done"]
STAGES_FULL = ["init", "crawl", "fetch", "check", "convert", "publish", "done"]


class TaskRunner:
    """全局单实例：同一时刻仅一个任务（FR-4.4）。"""

    _instance: "TaskRunner | None" = None
    _singleton_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: int | None = None
        self._cancel_events: dict[int, threading.Event] = {}
        self.engine: Engine = HermeticEngine(subscriptions=[], proxies=[])

    @classmethod
    def instance(cls) -> "TaskRunner":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ---------- 创建与校验 ----------
    def create(
        self,
        session: Session,
        *,
        mode: str,
        params: dict,
        source_ids: list[int],
        bind_target_ids: list[int],
        actor_id: int | None,
        trigger: str = "manual",
    ) -> CrawlRun:
        if mode not in ("crawl", "aggregate", "full"):
            raise ValueError("运行模式须为 crawl / aggregate / full")
        if mode != "crawl" and not bind_target_ids:
            raise ValueError("回测 / 爬取+聚合模式必须绑定至少一个已启用的存储目标")
        run = CrawlRun(
            run_uuid=str(uuid.uuid4()),
            trigger=trigger,
            mode=mode,
            status="pending",
            params={"num_threads": params.get("num_threads"), "bind_target_ids": list(bind_target_ids), **params},
            actor_id=actor_id,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    # ---------- 执行 ----------
    def start(self, run_id: int) -> bool:
        with self._lock:
            if self._current is not None:
                return False
            self._current = run_id
            self._cancel_events[run_id] = threading.Event()
        thread = threading.Thread(target=self._safe_execute, args=(run_id,), daemon=True)
        thread.start()
        return True

    def cancel(self, run_id: int) -> bool:
        event = self._cancel_events.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    def _safe_execute(self, run_id: int) -> None:
        session = db.SessionLocal()
        try:
            self._execute(session, run_id)
        except Exception as exc:  # noqa: BLE001 — 任务失败不拖垮 Web
            # 失败路径自身必须健壮：先落终态、再记日志，绝不让异常逃出线程
            # （曾因异常在已失败会话上继续 commit 导致线程死亡、run 卡在 running）
            try:
                session.rollback()
                run = session.get(CrawlRun, run_id)
                if run and run.status in ("pending", "running"):
                    run.status = "failed"
                    run.error = str(exc)
                    run.finished_at = _now()
                    run.duration_ms = _elapsed_ms(run.started_at)
                    session.commit()
            except Exception:  # noqa: BLE001 — 兜底：至少释放执行器锁
                logger.error(f"[Runner] failed to finalize run #{run_id} after error: {exc}")
            try:
                from .log_hub import log

                log(session, run_id, "ERROR", "runner", f"run #{run_id} failed: {exc}")
            except Exception:  # noqa: BLE001 — 日志写入失败不影响终态
                logger.error(f"[Runner] cannot write failure log for run #{run_id}: {exc}")
        finally:
            session.close()
            with self._lock:
                self._current = None
                self._cancel_events.pop(run_id, None)

    def _execute(self, session: Session, run_id: int) -> None:
        from .log_hub import capture_engine_logs, log

        run = session.get(CrawlRun, run_id)
        if run is None:
            return
        event = self._cancel_events.get(run_id, threading.Event())
        started = time.monotonic()
        run.status = "running"
        run.started_at = _now()
        run.stage = "init"
        session.commit()
        log(session, run_id, "INFO", "runner", f"run #{run_id} started, mode={run.mode}")

        ctx = RunContext(
            run_id=run_id,
            mode=run.mode,
            params=dict(run.params or {}),
            source_ids=list((run.params or {}).get("source_ids") or []),
            bind_target_ids=list((run.params or {}).get("bind_target_ids") or []),
            cancel_event=event,
        )
        outcome = EngineOutcome()

        def _stage(name: str) -> None:
            run.stage = name
            session.commit()

        try:
            with capture_engine_logs(run_id):
                if run.mode in ("crawl", "full"):
                    _stage("crawl")
                    crawl_outcome = self.engine.crawl(ctx)
                    outcome.subscriptions = crawl_outcome.subscriptions
                    outcome.loose = crawl_outcome.loose
                    _persist_subscriptions(session, run_id, outcome.subscriptions)
                    log(
                        session,
                        run_id,
                        "INFO",
                        "crawl",
                        f"subscriptions fetched: {len(outcome.subscriptions)}, loose nodes: {len(outcome.loose)}",
                    )

                if run.mode in ("aggregate", "full"):
                    pool, remains = _load_pool_and_remains(session, run_id)
                    log(
                        session,
                        run_id,
                        "INFO",
                        "pool",
                        f"系统库读取订阅池 {len(pool)} 条、remains {len(remains)} 节点（旧数据唯一来源）",
                    )
                    subscriptions = list(pool)
                    for url, _origin, reachable in outcome.subscriptions:
                        if reachable and url not in subscriptions:
                            subscriptions.append(url)
                    _stage("fetch")
                    proxies = self.engine.fetch(ctx, subscriptions, outcome.loose)
                    outcome.proxies = proxies
                    log(session, run_id, "INFO", "fetch", f"proxies fetched: {len(proxies)}")
                    _stage("check")
                    checked = proxies + remains
                    alive = self.engine.check(ctx, checked)
                    outcome.alive = alive
                    alive_keys = {_node_key(p) for p in alive}
                    log(
                        session,
                        run_id,
                        "INFO",
                        "check",
                        f"proxies check finished, total: {len(checked)}, alive: {len(alive)}",
                    )
                    _persist_nodes(session, run_id, checked, alive_keys)
                    _stage("convert")
                    outcome.artifacts = self.engine.convert(ctx, alive)
                    for spec in outcome.artifacts:
                        log(session, run_id, "INFO", "convert", f"artifact {spec['target']}: {spec['path']}")
                    _persist_artifacts(session, run_id, outcome.artifacts)
                    _stage("publish")
                    from .publisher import publish

                    pending = publish(session, run_id, outcome.artifacts, ctx.bind_target_ids)
                    if pending:
                        run.publish_pending = pending
                        run.status = "partial-success"
                        log(session, run_id, "WARNING", "publish", f"publish_pending: {pending}")
                    else:
                        run.status = "success"
                        log(session, run_id, "INFO", "publish", "publish completed")
                else:
                    run.status = "success"
        except RunCancelled:
            run.status = "cancelled"
            run.stage = run.stage or "cancelled"
            log(session, run_id, "WARNING", "runner", f"run #{run_id} cancelled")
        except Exception as exc:  # noqa: BLE001 — 任务失败不拖垮 Web
            log(session, run_id, "ERROR", "runner", f"run #{run_id} failed: {exc}")
            if run.status in ("pending", "running"):
                run.status = "failed"
                run.error = str(exc)

        run.stage = "done"
        run.finished_at = _now()
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.stats = _stats(run.mode, outcome)
        session.commit()
        log(session, run_id, "INFO", "runner", f"run #{run_id} finished, status={run.status}")


    # ---------- 状态查询 ----------
    @property
    def running_id(self) -> int | None:
        return self._current


def _persist_subscriptions(session: Session, run_id: int, subscriptions: list[tuple[str, str, bool]]) -> None:
    """订阅入库：批内按 url 去重（跨源可能重复命中；可达优先），单次提交。"""
    from datetime import datetime

    from models import Subscription

    merged: dict[str, tuple[str, bool]] = {}
    for url, origin, reachable in subscriptions:
        url = (url or "").strip()
        if not url:
            continue
        prev = merged.get(url)
        if prev is None or (reachable and not prev[1]):
            merged[url] = (origin, reachable)

    now = datetime.now()
    for url, (origin, reachable) in merged.items():
        row = session.query(Subscription).filter_by(url=url).first()
        if row is None:
            row = Subscription(url=url, origin=origin, first_seen_at=now)
            session.add(row)
        row.origin = origin
        row.last_seen_at = now
        row.status = "alive" if reachable else "pending"
        row.errors = 0 if reachable else (row.errors or 0) + 1
        if reachable:
            row.last_alive_at = now
    session.commit()


def _load_pool_and_remains(session: Session, run_id: int) -> tuple[list[str], list[dict]]:
    """订阅池 = 上轮 full/aggregate 存活节点的来源订阅；remains = 上轮存活节点（v2.3）。"""
    from models import Node

    last = (
        session.query(CrawlRun)
        .filter(CrawlRun.mode.in_(("full", "aggregate")), CrawlRun.status.in_(("success", "partial-success")))
        .filter(CrawlRun.id != run_id)
        .order_by(CrawlRun.id.desc())
        .first()
    )
    if last is None:
        return [], []
    nodes = session.query(Node).filter_by(run_id=last.id, alive=True).all()
    pool = []
    for node in nodes:
        if node.source_sub and node.source_sub not in pool:
            pool.append(node.source_sub)
    remains = [dict(n.raw) | {"name": n.name, "delay": n.delay_ms} for n in nodes]
    return pool, remains


def _persist_nodes(session: Session, run_id: int, checked: list[dict], alive_keys: set[str] | None = None) -> None:
    """节点入库：全部被检节点（含失效），按 fetch 标记区分散节点/订阅节点。

    alive_keys 为 None 时视为全部存活（测试替身语义）；否则按 server:port:type 判定。
    """
    from models import Node

    for proxy in checked:
        raw = {k: v for k, v in proxy.items() if k not in ("_kind", "_source", "_source_sub")}
        alive = True if alive_keys is None else _node_key(proxy) in alive_keys
        session.add(
            Node(
                run_id=run_id,
                name=str(proxy.get("name", "")),
                protocol=str(proxy.get("type", "")).lower(),
                server=str(proxy.get("server", "")),
                port=int(proxy.get("port", 0) or 0),
                kind=proxy.get("_kind", "sub"),
                source=proxy.get("_source"),
                source_sub=proxy.get("_source_sub") or proxy.get("sub"),
                delay_ms=proxy.get("delay"),
                alive=alive,
                raw=raw,
            )
        )
    session.commit()


def _node_key(proxy: dict) -> str:
    return f"{proxy.get('server', '')}:{proxy.get('port', '')}:{proxy.get('type', '')}"


def _persist_artifacts(session: Session, run_id: int, artifacts: list[dict]) -> None:
    from models import Artifact

    for spec in artifacts:
        session.add(
            Artifact(
                run_id=run_id,
                target=spec["target"],
                path=spec["path"],
                size=int(spec.get("size", 0) or 0),
            )
        )
    session.commit()


def _stats(mode: str, outcome: EngineOutcome) -> dict:
    stats: dict = {}
    if mode in ("crawl", "full"):
        stats["subs_total"] = len(outcome.subscriptions)
        stats["subs_alive"] = sum(1 for _u, _o, ok in outcome.subscriptions if ok)
    if mode in ("aggregate", "full"):
        stats["nodes_total"] = len(outcome.proxies)
        stats["nodes_alive"] = len(outcome.alive)
        stats["artifacts"] = [
            {"target": a["target"], "path": a["path"], "size": a.get("size")} for a in outcome.artifacts
        ]
    return stats


def _now():
    from datetime import datetime

    return datetime.now()


def _elapsed_ms(started) -> int:
    from datetime import datetime

    if not started:
        return 0
    return int((datetime.now() - started).total_seconds() * 1000)
