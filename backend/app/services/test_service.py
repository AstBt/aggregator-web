# -*- coding: utf-8 -*-
"""状态测试服务：订阅并发探测 + 节点验活（结果板块「测试状态」按钮）。

- 订阅测试：check_status 可达性 + 节点数计数（不落节点表，只更新状态与计数）
- 节点测试：自管 mihomo 控制器并发查询延迟；地区/住宅经引擎同源的
  location.batch_query（每节点独立监听端口）完成，避免经默认出口误判
- 测试任务为进程内注册表（单实例、可查询进度），与 TaskRunner 的长任务互不阻塞
"""

from __future__ import annotations

import json
import socket
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path

import db
from models import Node, Subscription
from sqlalchemy import select

PROJECT_DIR = Path(__file__).resolve().parents[3]
CLASH_DIR = PROJECT_DIR / "clash"

# 节点测试阶段（前端映射为中文标签展示）
PHASE_DELAY = "delay"
PHASE_LOCATE = "locate"

DEFAULT_TEST_URL = "https://www.google.com/generate_204"
DEFAULT_PARAMS = {"num_threads": 16, "max_delay": 5000, "timeout": 5000, "test_url": DEFAULT_TEST_URL}


@dataclass
class TestJob:
    job_id: str
    kind: str  # subscription / node
    total: int
    done: int = 0
    status: str = "running"  # running / success / failed
    message: str = ""
    phase: str = ""  # 节点测试当前阶段（delay / locate），订阅测试为空
    created_at: datetime = field(default_factory=datetime.now)


class TestHub:
    """进程内测试任务注册表（重启后清空，属于瞬时状态）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, TestJob] = {}

    def create(self, kind: str, total: int) -> TestJob:
        job = TestJob(job_id=uuid.uuid4(), kind=kind, total=total)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> TestJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 20) -> list[TestJob]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def advance(self, job_id: str, n: int = 1) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.done = min(job.total, job.done + n)

    def begin_phase(self, job_id: str, phase: str) -> None:
        """进入新阶段：重置进度并更新阶段标签（节点测试测速/定位分段展示）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.phase = phase
                job.done = 0

    def finish(self, job_id: str, status: str, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = status
                job.message = message
                job.done = job.total


hub = TestHub()


def _resolve_params(params: dict | None) -> dict:
    """测试参数：显式传值优先，缺省取「验活参数」页设置（与任务执行同源）。"""
    merged = dict(DEFAULT_PARAMS)
    try:
        session = db.SessionLocal()
        try:
            from services import settings_service

            alive = settings_service.get_alive(session)
        finally:
            session.close()
        for key in ("num_threads", "max_delay", "timeout"):
            if alive.get(key):
                merged[key] = int(alive[key])
        url = alive.get("primary_test_url") or (alive.get("test_urls") or [None])[0]
        if url:
            merged["test_url"] = str(url)
    except Exception:  # noqa: BLE001 — 设置缺失时退回内置默认值
        pass
    for key, value in (params or {}).items():
        if value is not None:
            merged[key] = value
    return merged


# ---------- 订阅测试 ----------
def _probe_subscription(url: str) -> tuple[bool, int]:
    """探测单个订阅：可达性 + 节点数（默认实现，测试可 monkeypatch）。"""
    import sys

    if str(PROJECT_DIR / "subscribe") not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR / "subscribe"))
    from crawl.helpers import check_status

    available, _expired = check_status(url, retry=2, proxy="")
    if not available:
        return False, 0
    return True, _count_sub_nodes(url)


def _count_sub_nodes(url: str) -> int:
    """拉取订阅文本并统计协议链接数（轻量计数，不写库）。"""
    import base64
    import re
    import sys

    if str(PROJECT_DIR / "subscribe") not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR / "subscribe"))
    try:
        import utils
        from crawl.extract import PROTOCOL_REGEX
    except Exception:
        return 0
    text = utils.http_get(url=url, retry=1, timeout=12) or ""
    if not text:
        return 0
    if utils.isb64encode(content=text):
        try:
            text = base64.b64decode(text).decode("utf-8", "ignore")
        except Exception:
            pass
    found = re.findall(PROTOCOL_REGEX, text, flags=re.I)
    return len({x.strip() for x in found if x.strip()})


def test_subscriptions(ids: list[int] | None = None, concurrency: int = 8) -> TestJob:
    """对勾选订阅（或全部）并发测试状态。"""
    session = db.SessionLocal()
    try:
        stmt = select(Subscription)
        if ids:
            stmt = stmt.where(Subscription.id.in_(ids))
        targets = session.scalars(stmt).all()
    finally:
        session.close()
    if not targets:
        raise ValueError("没有匹配的订阅")

    job = hub.create("subscription", len(targets))
    mark_testing([t.id for t in targets])

    def worker() -> None:
        from concurrent.futures import ThreadPoolExecutor

        def one(sub_id: int) -> None:
            s = db.SessionLocal()
            try:
                row = s.get(Subscription, sub_id)
                if row is None:
                    return
                try:
                    available, count = _probe_subscription(row.url)
                except Exception:
                    available, count = False, 0
                row.status = "alive" if available else "dead"
                row.errors = 0 if available else row.errors + 1
                row.last_seen_at = datetime.now()
                if available:
                    row.last_alive_at = datetime.now()
                    row.node_count = count
                s.commit()
            finally:
                s.close()
                hub.advance(job.job_id)

        try:
            with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
                list(pool.map(one, [t.id for t in targets]))
            hub.finish(job.job_id, "success")
        except Exception as exc:  # noqa: BLE001
            hub.finish(job.job_id, "failed", str(exc))

    threading.Thread(target=worker, daemon=True).start()
    return job


def mark_testing(ids: list[int]) -> None:
    session = db.SessionLocal()
    try:
        for sub_id in ids:
            row = session.get(Subscription, sub_id)
            if row:
                row.status = "testing"
        session.commit()
    finally:
        session.close()


# ---------- 节点测试 ----------
def _check_alive(proxies: list[dict], **kwargs) -> dict:
    """对节点跑 mihomo 延迟探测，返回 {node_key: delay_ms}（不含测试替身逻辑）。

    与 pipeline.check_alive_proxies 同源：独立控制器 + 并发查询延迟端点，
    但这里回传实测延迟值供「测试节点状态」落库（后者只返回存活列表）。
    """
    import sys

    if str(PROJECT_DIR / "subscribe") not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR / "subscribe"))
    import executable

    clash_bin, _ = executable.which_bin()
    binpath = CLASH_DIR / clash_bin
    if not binpath.is_file():
        raise ValueError(f"clash 二进制不存在: {binpath}")

    import clash
    import pipeline

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        controller = f"127.0.0.1:{listener.getsockname()[1]}"

    delay_limit = int(kwargs.get("max_delay", 5000))
    query_timeout = max(2, int(kwargs.get("timeout", 5000)) / 1000 + 2)
    process = None
    with tempfile.TemporaryDirectory(prefix="agg-nodetest-") as directory:
        candidates = clash.generate_config(
            directory, [dict(p) for p in proxies], "config.yaml", controller=controller
        )

        def probe(item: dict) -> tuple[str, int | None]:
            name = urllib.parse.quote(str(item.get("name", "")), safe="")
            query = urllib.parse.urlencode({"timeout": int(kwargs.get("timeout", 5000)), "url": kwargs.get("test_url", DEFAULT_TEST_URL)})
            request = urllib.request.Request(f"http://{controller}/proxies/{name}/delay?{query}")
            try:
                with urllib.request.urlopen(request, timeout=query_timeout) as resp:
                    value = json.loads(resp.read()).get("delay", -1)
            except Exception:
                return _node_key(item), None
            if isinstance(value, (int, float)) and 0 <= value <= delay_limit:
                return _node_key(item), int(value)
            return _node_key(item), None

        try:
            process = subprocess.Popen(
                [str(binpath), "-d", str(CLASH_DIR), "-f", str(Path(directory) / "config.yaml")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pipeline._wait_for_controller(process, controller)
            threads = min(max(1, int(kwargs.get("num_threads", 16))), 32)
            measured: dict[str, int] = {}
            with ThreadPoolExecutor(max_workers=threads) as pool:
                futures = [pool.submit(probe, item) for item in candidates]
                for future in as_completed(futures):
                    key, delay = future.result()
                    if delay is not None:
                        measured[key] = delay
                    on_probed = kwargs.get("on_probed")
                    if on_probed:
                        on_probed()
            return measured
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


def _load_mmdb_reader():
    """加载本地 Country.mmdb（缺失/损坏时返回 None，地区退化为未知）。"""
    mmdb = CLASH_DIR / "Country.mmdb"
    if not mmdb.is_file():
        return None
    try:
        from geoip2 import database

        return database.Reader(str(mmdb))
    except Exception:
        return None


def _mmdb_region(proxy: dict, reader) -> tuple[str, str | None]:
    """经服务器地址本地解析地区（不经过节点，失效节点也可用）。"""
    key = _node_key(proxy)
    if reader is None:
        return key, None
    try:
        import socket as _socket

        ip = _socket.gethostbyname(str(proxy.get("server", "")))
        country = (reader.country(ip).country.names or {}).get("zh-CN", "")
        return key, country or None
    except Exception:
        return key, None


def _probe_locate(
    proxies: list[dict], residential: bool, params: dict | None = None, alive_keys=None, on_located=None
) -> dict:
    """地区 + 住宅判定，返回 {node_key: {region, residential}}。

    - 地区优先取情报库经节点出口的实测结果；出口不可达时退回 mmdb 本地解析
    - 住宅判定仅对存活节点发起（经节点出口查询），失效节点跳过以节省时间
    - 复用引擎同源的 location.batch_query：每节点独立监听端口，避免经默认出口误判
    """
    import sys

    if str(PROJECT_DIR / "subscribe") not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    threads = min(max(1, int((params or {}).get("num_threads", 16))), 32)
    reader = _load_mmdb_reader()
    mapping: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(_mmdb_region, dict(p), reader) for p in proxies]
        for future in as_completed(futures):
            key, country = future.result()
            if country:
                mapping[key] = {"region": country}
            if on_located:
                on_located()

    if residential:
        alive_proxies = [dict(p) for p in proxies if alive_keys is None or _node_key(p) in alive_keys]
        if alive_proxies:
            if str(PROJECT_DIR / "subscribe") not in sys.path:
                sys.path.insert(0, str(PROJECT_DIR / "subscribe"))
            import location

            results = location.batch_query(
                proxies=alive_proxies,
                func=partial(location.check_residential, reader=reader),
                num_threads=threads,
                show_progress=False,
            )
            for item in results or []:
                if item is not None and item.success and item.result.country:
                    mapping[_node_key(item.proxy)] = {
                        "region": item.result.country,
                        "residential": item.result.ip_type == "isp",
                    }
    return mapping


def test_nodes(
    ids: list[int] | None = None, locate: bool = True, residential: bool = True, params: dict | None = None
) -> TestJob:
    """对勾选节点（或散节点全部）执行验活并更新状态。"""
    resolved = _resolve_params(params)
    session = db.SessionLocal()
    try:
        stmt = select(Node).where(Node.kind == "crawl")
        if ids:
            stmt = stmt.where(Node.id.in_(ids))
        rows = session.scalars(stmt).all()
        snapshots = [(r.id, dict(r.raw or {})) for r in rows]
    finally:
        session.close()
    if not snapshots:
        raise ValueError("没有匹配的节点")

    job = hub.create("node", len(snapshots))

    def worker() -> None:
        try:
            proxies = [raw for _nid, raw in snapshots]
            hub.begin_phase(job.job_id, PHASE_DELAY)
            delays = _check_alive(
                proxies,
                max_delay=resolved["max_delay"],
                timeout=resolved["timeout"],
                test_url=resolved["test_url"],
                num_threads=resolved["num_threads"],
                on_probed=lambda: hub.advance(job.job_id),
            )
            infos = {}
            if locate:
                hub.begin_phase(job.job_id, PHASE_LOCATE)
                infos = _probe_locate(
                    proxies,
                    residential=residential,
                    params=resolved,
                    alive_keys=set(delays),
                    on_located=lambda: hub.advance(job.job_id),
                )
            s = db.SessionLocal()
            try:
                for nid, raw in snapshots:
                    row = s.get(Node, nid)
                    if row is None:
                        continue
                    key = _node_key(raw)
                    delay = delays.get(key)
                    row.alive = delay is not None
                    row.delay_ms = delay  # 失效即清空，不保留上一轮实测值
                    info = infos.get(key) or {}
                    if info.get("region"):
                        row.region = info["region"]
                    if "residential" in info and info["residential"] is not None:
                        row.residential = info["residential"]
                    s.commit()
            finally:
                s.close()
            hub.finish(job.job_id, "success")
        except Exception as exc:  # noqa: BLE001
            hub.finish(job.job_id, "failed", str(exc))

    threading.Thread(target=worker, daemon=True).start()
    return job


def _node_key(proxy: dict) -> str:
    return f"{proxy.get('server', '')}:{proxy.get('port', '')}:{proxy.get('type', '')}"
