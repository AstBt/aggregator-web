# -*- coding: utf-8 -*-
"""状态测试服务：订阅并发探测 + 节点验活（结果板块「测试状态」按钮）。

- 订阅测试：check_status 可达性 + 节点数计数（不落节点表，只更新状态与计数）
- 节点测试：自管 mihomo 控制器查询延迟/存活，并按需做 mmdb 地区与住宅判定；
  不重命名节点（区别于引擎管线的 location.regularize）
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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import db
from models import Node, Subscription
from sqlalchemy import select

PROJECT_DIR = Path(__file__).resolve().parents[3]
CLASH_DIR = PROJECT_DIR / "clash"
TERMINAL = ("success", "failed")


@dataclass
class TestJob:
    job_id: str
    kind: str  # subscription / node
    total: int
    done: int = 0
    status: str = "running"  # running / success / failed
    message: str = ""
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

    def finish(self, job_id: str, status: str, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = status
                job.message = message
                job.done = job.total


hub = TestHub()


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

    与 pipeline.check_alive_proxies 的区别：后者只返回存活列表、不回传实测延迟；
    这里复用它同源的控制器装配（clash.generate_config + 独立端口），逐节点查询
    延迟端点，用于「测试节点状态」后的状态更新。
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
    process = None
    with tempfile.TemporaryDirectory(prefix="agg-nodetest-") as directory:
        candidates = clash.generate_config(
            directory, [dict(p) for p in proxies], "config.yaml", controller=controller
        )
        try:
            process = subprocess.Popen(
                [str(binpath), "-d", str(CLASH_DIR), "-f", str(Path(directory) / "config.yaml")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            pipeline._wait_for_controller(process, controller)
            measured: dict[str, int] = {}
            for item in candidates:
                name = urllib.parse.quote(str(item.get("name", "")), safe="")
                query = urllib.parse.urlencode({"timeout": int(kwargs.get("timeout", 5000)), "url": kwargs.get("test_url", "https://www.google.com/generate_204")})
                request = urllib.request.Request(f"http://{controller}/proxies/{name}/delay?{query}")
                try:
                    with urllib.request.urlopen(request, timeout=max(2, int(kwargs.get("timeout", 5000)) / 1000 + 2)) as resp:
                        value = json.loads(resp.read()).get("delay", -1)
                    if isinstance(value, (int, float)) and 0 <= value <= delay_limit:
                        measured[_node_key(item)] = int(value)
                except Exception:
                    continue
            return measured
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


def _probe_locate(proxies: list[dict], residential: bool) -> dict:
    """地区（mmdb）+ 住宅（经节点出口查询情报库），返回 {node_key: {region, residential}}。"""
    import sys

    if str(PROJECT_DIR / "subscribe") not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    mapping: dict[str, dict] = {}

    reader = None
    mmdb = CLASH_DIR / "Country.mmdb"
    if mmdb.is_file():
        try:
            from geoip2 import database

            reader = database.Reader(str(mmdb))
        except Exception:
            reader = None

    if residential:
        import sys

        if str(PROJECT_DIR / "subscribe") not in sys.path:
            sys.path.insert(0, str(PROJECT_DIR / "subscribe"))
        import executable
        import location

        clash_bin, _ = executable.which_bin()
        binpath = CLASH_DIR / clash_bin
        if binpath.is_file():
            import clash
            import pipeline

            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            process = None
            with tempfile.TemporaryDirectory(prefix="agg-locate-") as directory:
                controller = f"127.0.0.1:{port}"
                candidates = clash.generate_config(
                    directory, [dict(p) for p in proxies], "config.yaml", controller=controller
                )
                try:
                    process = subprocess.Popen(
                        [str(binpath), "-d", str(CLASH_DIR), "-f", str(Path(directory) / "config.yaml")],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    pipeline._wait_for_controller(process, controller)
                    for item in candidates:
                        try:
                            info = location.check_residential(item, port, reader=reader)
                        except Exception:
                            continue
                        if info.success and info.result.country:
                            mapping[_node_key(item)] = {
                                "region": info.result.country,
                                "residential": info.result.ip_type == "isp",
                            }
                finally:
                    if process is not None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
    if reader is not None:
        import socket as _socket

        for proxy in proxies:
            key = _node_key(proxy)
            if key in mapping:
                continue
            try:
                ip = _socket.gethostbyname(str(proxy.get("server", "")))
                resp = reader.country(ip)
                country = (resp.country.names or {}).get("zh-CN", "")
                if country:
                    mapping[key] = {"region": country}
            except Exception:
                continue
    return mapping


def test_nodes(
    ids: list[int] | None = None, locate: bool = True, residential: bool = True, params: dict | None = None
) -> TestJob:
    """对勾选节点（或散节点全部）执行验活并更新状态。"""
    params = params or {}
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
            delays = _check_alive(proxies, **params)
            infos = _probe_locate(proxies, residential=residential) if locate else {}
            s = db.SessionLocal()
            try:
                for nid, raw in snapshots:
                    row = s.get(Node, nid)
                    if row is None:
                        continue
                    key = _node_key(raw)
                    delay = delays.get(key)
                    row.alive = delay is not None
                    if delay is not None:
                        row.delay_ms = delay
                    info = infos.get(key) or {}
                    if info.get("region"):
                        row.region = info["region"]
                    if "residential" in info and info["residential"] is not None:
                        row.residential = info["residential"]
                    s.commit()
                    hub.advance(job.job_id)
            finally:
                s.close()
            hub.finish(job.job_id, "success")
        except Exception as exc:  # noqa: BLE001
            hub.finish(job.job_id, "failed", str(exc))

    threading.Thread(target=worker, daemon=True).start()
    return job


def _node_key(proxy: dict) -> str:
    return f"{proxy.get('server', '')}:{proxy.get('port', '')}:{proxy.get('type', '')}"
