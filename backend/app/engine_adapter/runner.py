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
    pool_size: int = 0  # 本轮复核的旧订阅池规模
    verified_subs: int = 0  # 验活确认可用（产出存活节点）的订阅数


class Engine(Protocol):
    """引擎协议：抓取→（可选）订阅验证→拉取→验活→转换；真实实现见 engine.py。

    validate 为可选方法：未实现时 runner 沿用 crawl 返回的可达标记（测试替身语义）。
    """

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
        source_sub = subscriptions[0] if subscriptions else ""
        return [{**p, "_kind": "sub", "_source_sub": source_sub} for p in self._proxies]

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


STAGES_CRAWL = ["init", "crawl", "validate", "done"]
STAGES_AGGREGATE = ["init", "fetch", "check", "convert", "publish", "done"]
STAGES_FULL = ["init", "crawl", "validate", "fetch", "check", "convert", "publish", "done"]


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
            from .engine import proxy_scope

            with capture_engine_logs(run_id), proxy_scope(session) as proxy:
                if proxy.applied:
                    log(session, run_id, "INFO", "runner", f"本地代理已启用（{proxy.applied}）：爬取/订阅验证/拉取/发布经代理中转，节点验活仍直连")
                if run.mode in ("crawl", "full"):
                    _stage("crawl")
                    crawl_outcome = self.engine.crawl(ctx)
                    outcome.subscriptions = crawl_outcome.subscriptions
                    outcome.loose = crawl_outcome.loose
                    log(
                        session,
                        run_id,
                        "INFO",
                        "crawl",
                        f"subscriptions fetched: {len(outcome.subscriptions)}, loose nodes: {len(outcome.loose)}",
                    )
                    # 订阅验证独立成阶段：数千订阅的可达性探测可能持续数十分钟，必须有阶段与进度可见
                    _stage("validate")
                    reachable = _validate_outcome(self.engine, ctx, outcome.subscriptions)
                    outcome.subscriptions = [
                        (url, origin, reachable.get(url, ok)) for url, origin, ok in outcome.subscriptions
                    ]
                    validated = sum(1 for *_t, ok in outcome.subscriptions if ok)
                    log(
                        session,
                        run_id,
                        "INFO",
                        "validate",
                        f"subscriptions validated: {validated}/{len(outcome.subscriptions)} reachable",
                    )
                    if run.mode == "crawl":
                        # 仅爬取：订阅级验证（可达性）通过才入订阅池；散节点未验活不入节点库
                        persisted = _persist_validated_subscriptions(session, outcome.subscriptions)
                        log(
                            session,
                            run_id,
                            "INFO",
                            "crawl",
                            f"validated into pool: {persisted}, loose nodes (unverified, not stored): {len(outcome.loose)}",
                        )

                if run.mode in ("aggregate", "full"):
                    pool, remains = _load_pool_and_remains(session)
                    outcome.pool_size = len(pool)
                    log(
                        session,
                        run_id,
                        "INFO",
                        "pool",
                        f"系统库读取订阅池 {len(pool)} 条、可用节点 {len(remains)} 个（复核对象 = 之前验活确认可用数据）",
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
                    log(
                        session,
                        run_id,
                        "INFO",
                        "check",
                        f"proxies check finished, total: {len(checked)}, alive: {len(alive)}",
                    )
                    # 验活后才写库：订阅结果仅存「存活且产出可用节点」者，节点库整体替换为存活集
                    outcome.verified_subs = _persist_verified(session, run_id, alive, outcome.subscriptions)
                    log(
                        session,
                        run_id,
                        "INFO",
                        "persist",
                        f"verified subscriptions into pool: {outcome.verified_subs}, alive nodes stored: {len(alive)}",
                    )
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


def _validate_outcome(engine: Engine, ctx: RunContext, subscriptions: list[tuple[str, str, bool]]) -> dict[str, bool]:
    """订阅可达性验证：引擎提供 validate 方法时以其结果为准；否则保留 crawl 阶段自带标记。

    返回 {url: reachable}；空 dict 表示沿用原标记（测试替身/脚本引擎的默认语义）。
    """
    validate = getattr(engine, "validate", None)
    if validate is None:
        return {}
    return validate(ctx, [url for url, _origin, _ok in subscriptions]) or {}


def _max_fails(session: Session) -> int:
    """旧订阅复核失败的容忍次数（爬取参数页 max_fails），达到即移出订阅池。"""
    from models import Setting

    setting = session.get(Setting, "crawl")
    value = (dict(setting.value) if setting else {}).get("max_fails")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


def _persist_validated_subscriptions(session: Session, subscriptions: list[tuple[str, str, bool]]) -> int:
    """仅爬取模式订阅入库：仅订阅级验证（可达性）通过者入订阅池。

    - 新订阅不可达：不入库（订阅结果不保存未验证数据）
    - 已有订阅本次不可达：复核失败计数 +1，达 max_fails 移出订阅池
    返回本轮入库（验证通过）的订阅数。
    """
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

    max_fails = _max_fails(session)
    now = datetime.now()
    persisted = 0
    for url, (origin, reachable) in merged.items():
        row = session.query(Subscription).filter_by(url=url).first()
        if reachable:
            if row is None:
                row = Subscription(url=url, origin=origin, first_seen_at=now)
                session.add(row)
            row.origin = origin
            row.status = "alive"
            row.errors = 0
            row.last_seen_at = now
            row.last_alive_at = now
            persisted += 1
        elif row is not None:
            row.errors = (row.errors or 0) + 1
            row.status = "dead"
            row.last_seen_at = now
            if row.errors >= max_fails:
                session.delete(row)
    session.commit()
    return persisted


def _load_pool_and_remains(session: Session) -> tuple[list[str], list[dict]]:
    """旧数据复核集 = 系统库当前可用数据：订阅池（订阅表全部行）+ 可用节点（节点库全部行）。

    系统库只保存验活确认可用的数据，因此直接读表即为「之前任务验活后确认可用」的复核对象；
    remains 附带 _kind/_source/_source_sub 标记，复核存活后入库仍保留来源归属。
    """
    from models import Node, Subscription

    pool = [row.url for row in session.query(Subscription).order_by(Subscription.id)]
    remains = []
    for node in session.query(Node).order_by(Node.id):
        raw = dict(node.raw or {})
        raw.update(
            {
                "name": node.name,
                "delay": node.delay_ms,
                "_kind": node.kind,
                "_source": node.source,
                "_source_sub": node.source_sub,
            }
        )
        remains.append(raw)
    return pool, remains


def _persist_verified(
    session: Session, run_id: int, alive: list[dict], discovered: list[tuple[str, str, bool]]
) -> int:
    """验活后写库（单次提交准事务）：订阅结果与节点库只保留验活确认可用的数据。

    - 订阅结果：仅「验活存活且产出可用节点」的订阅入库/更新（node_count=本轮存活节点数）；
      旧订阅复核失败计数 +1 并标记失效，连续失败达 max_fails 移出订阅池
    - 节点库：整体替换为本次验活存活集（含旧节点复核存活者，来源归属随 remains 标记保留）
    返回本轮确认可用的订阅数。
    """
    from datetime import datetime

    from models import Node, Subscription

    now = datetime.now()
    max_fails = _max_fails(session)
    origins = {(url or "").strip(): origin for url, origin, _ok in discovered if (url or "").strip()}

    # 订阅维度：本轮各订阅产出的存活节点数
    sub_alive_count: dict[str, int] = {}
    for proxy in alive:
        source_sub = proxy.get("_source_sub")
        if proxy.get("_kind") == "sub" and source_sub:
            sub_alive_count[source_sub] = sub_alive_count.get(source_sub, 0) + 1

    for url, count in sub_alive_count.items():
        row = session.query(Subscription).filter_by(url=url).first()
        if row is None:
            row = Subscription(url=url, origin=origins.get(url, "TEMPORARY"), first_seen_at=now)
            session.add(row)
        row.status = "alive"
        row.errors = 0
        row.node_count = count
        row.last_seen_at = now
        row.last_alive_at = now

    verified = set(sub_alive_count)
    for row in session.query(Subscription).all():
        if row.url in verified:
            continue
        row.errors = (row.errors or 0) + 1
        row.status = "dead"
        row.node_count = 0
        row.last_seen_at = now
        if row.errors >= max_fails:
            session.delete(row)

    # 节点库整体替换（同一事务内删除+写入，失败回滚则系统库保持原状）
    session.query(Node).delete()
    session.flush()
    for proxy in alive:
        raw = {k: v for k, v in proxy.items() if k not in ("_kind", "_source", "_source_sub")}
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
                alive=True,
                raw=raw,
            )
        )
    session.commit()
    return len(verified)


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
        # 按 URL 去重后计数：与订阅池入库口径一致（跨源重复命中只算一条）
        unique_urls = {(url or "").strip() for url, _origin, _ok in outcome.subscriptions if (url or "").strip()}
        stats["subs_total"] = len(unique_urls)
        alive_urls = {
            (url or "").strip() for url, _origin, ok in outcome.subscriptions if ok and (url or "").strip()
        }
        stats["subs_alive"] = len(alive_urls)
    if mode in ("aggregate", "full"):
        if mode == "aggregate":
            stats["subs_total"] = outcome.pool_size
        stats["subs_usable"] = outcome.verified_subs
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
