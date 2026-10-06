# -*- coding: utf-8 -*-
"""任务执行器测试（FR-4.1~4.10, A8~A11/A16）。"""

from __future__ import annotations

import time

import pytest

from conftest import auth_header




def _wait_run(client, token, run_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/tasks/{run_id}", headers=auth_header(token)).json()["data"]
        if data["status"] in ("success", "failed", "cancelled", "partial-success"):
            return data
        time.sleep(0.2)
    raise AssertionError("run 未在超时前结束")


class TestCreateTask:
    def test_crawl_only_requires_no_binding(self, client, operator_token, fake_engine):
        resp = client.post(
            "/api/tasks",
            json={"mode": "crawl", "params": {"num_threads": 8}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["mode"] == "crawl"
        assert resp.json()["data"]["status"] == "pending"

    def test_full_requires_binding(self, client, operator_token, fake_engine):
        resp = client.post("/api/tasks", json={"mode": "full"}, headers=auth_header(operator_token))
        assert resp.status_code == 400
        assert "绑定" in resp.json()["message"]

    def test_aggregate_requires_binding(self, client, operator_token, fake_engine):
        resp = client.post("/api/tasks", json={"mode": "aggregate"}, headers=auth_header(operator_token))
        assert resp.status_code == 400

    def test_binding_disabled_target_rejected(self, client, operator_token, fake_engine, db_session):
        from models import StorageTarget

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        target.enable = False
        db_session.commit()
        resp = client.post(
            "/api/tasks",
            json={"mode": "full", "bind_target_ids": [target.id]},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400

    def test_viewer_cannot_create(self, client, admin_token, fake_engine):
        client.post(
            "/api/users",
            json={"username": "viewer3", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer3", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.post("/api/tasks", json={"mode": "crawl"}, headers=auth_header(viewer)).status_code == 403


class TestRunLifecycle:
    def test_crawl_run_completes_with_stats(self, client, operator_token, fake_engine):
        run_id = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        data = _wait_run(client, operator_token, run_id)
        assert data["status"] == "success"
        assert data["stats"]["subs_alive"] == 1
        assert data["stage"] == "done"

    def test_crawl_stats_count_unique_subscriptions(self, client, operator_token, monkeypatch):
        """订阅统计按 URL 去重后计数，与订阅池条数一致（跨源重复命中只算一次）。"""
        from engine_adapter import runner as runner_module

        engine = runner_module.HermeticEngine(
            subscriptions=[
                ("https://dup.example.com/a", "PAGE", True),
                ("https://dup.example.com/a", "GITHUB", True),
                ("https://uniq.example.com/b", "PAGE", False),
            ],
            proxies=[],
        )
        previous = runner_module.TaskRunner.instance().engine
        runner_module.TaskRunner.instance().engine = engine
        try:
            run_id = client.post(
                "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
            ).json()["data"]["id"]
            data = _wait_run(client, operator_token, run_id)
        finally:
            runner_module.TaskRunner.instance().engine = previous
        assert data["stats"]["subs_total"] == 2
        assert data["stats"]["subs_alive"] == 1

    def test_full_run_publishes_to_bound_targets(self, client, operator_token, fake_engine, db_session, tmp_path):
        from models import StorageTarget

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        target.config = {"dir": str(tmp_path / "local"), "keep": 5}
        db_session.commit()
        run_id = client.post(
            "/api/tasks",
            json={"mode": "full", "bind_target_ids": [target.id]},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        data = _wait_run(client, operator_token, run_id)
        assert data["status"] == "success"
        assert data["stats"]["nodes_alive"] == 3
        written = list((tmp_path / "local").glob("*"))
        assert written, "绑定目标应收到产物"

    def test_aggregate_reads_pool_from_system_db(self, client, operator_token, fake_engine, db_session):
        """回测：旧订阅池/remains 来自系统库（v2.3 决策）。"""
        from models import Node, RunLog, Subscription

        # 预置上轮存活订阅与节点
        db_session.add(Subscription(url="https://old.example.com/pool", origin="PAGE", status="alive"))
        prev = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        run = _wait_run(client, operator_token, prev)
        # 回测任务
        target = db_session.query(StorageTarget := __import__("models").StorageTarget).filter_by(name="data-local").first()
        run_id = client.post(
            "/api/tasks",
            json={"mode": "aggregate", "bind_target_ids": [target.id]},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        data = _wait_run(client, operator_token, run_id)
        logs = [
            row.message
            for row in db_session.query(RunLog).filter_by(run_id=run_id).all()
        ]
        assert any("系统库" in m for m in logs), logs

    def test_global_mutex_409(self, client, operator_token, fake_engine):
        """全局单实例：任何模式互斥（含回测在跑，FR-4.4）。"""
        from engine_adapter import runner as runner_module

        class SlowEngine(runner_module.HermeticEngine):
            def crawl(self, ctx):
                import time as _t

                for _ in range(30):
                    ctx.check_cancelled()
                    _t.sleep(0.1)
                return super().crawl(ctx)

        runner = runner_module.TaskRunner.instance()
        runner.engine = SlowEngine(subscriptions=[], proxies=[])
        try:
            run_id = client.post(
                "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
            ).json()["data"]["id"]
            resp = client.post(
                "/api/tasks",
                json={"mode": "aggregate", "bind_target_ids": [1]},
                headers=auth_header(operator_token),
            )
            assert resp.status_code == 409
            assert "正在运行" in resp.json()["message"]
        finally:
            client.post(f"/api/tasks/{run_id}/cancel", headers=auth_header(operator_token))


class TestCancelAndLogs:
    def test_cancel_marks_cancelled(self, client, operator_token):
        from engine_adapter import runner as runner_module

        class HoldEngine(runner_module.HermeticEngine):
            def crawl(self, ctx):
                import time as _t

                for _ in range(50):
                    if ctx.cancelled:
                        raise runner_module.RunCancelled()
                    _t.sleep(0.1)
                return super().crawl(ctx)

        previous = runner_module.TaskRunner.instance().engine
        runner_module.TaskRunner.instance().engine = HoldEngine(subscriptions=[], proxies=[])
        run_id = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        time.sleep(0.5)
        resp = client.post(f"/api/tasks/{run_id}/cancel", headers=auth_header(operator_token))
        assert resp.status_code == 200
        data = _wait_run(client, operator_token, run_id)
        assert data["status"] == "cancelled"
        runner_module.TaskRunner.instance().engine = previous

    def test_logs_incremental(self, client, operator_token, fake_engine):
        run_id = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        _wait_run(client, operator_token, run_id)
        first = client.get(f"/api/tasks/{run_id}/logs", headers=auth_header(operator_token)).json()["data"]
        assert first["items"], "应有日志"
        assert first["items"][0]["id"]
        cursor = first["items"][0]["id"]
        second = client.get(
            f"/api/tasks/{run_id}/logs?since={cursor}", headers=auth_header(operator_token)
        ).json()["data"]
        assert all(item["id"] > cursor for item in second["items"])


class TestSchedulerTranslation:
    def test_six_interval_kinds_to_cron(self):
        from services import scheduler_service

        assert scheduler_service.to_cron("minute", n=30) == "*/30 * * * *"
        assert scheduler_service.to_cron("hour", n=6) == "0 */6 * * *"
        assert scheduler_service.to_cron("daily", time="09:00") == "0 9 * * *"
        assert scheduler_service.to_cron("weekly", weekdays=[1], time="09:00") == "0 9 * * 1"
        assert scheduler_service.to_cron("day", n=3, time="11:05") == "5 11 */3 * *"
        assert scheduler_service.to_cron("week", n=2, weekdays=[6]) == "0 0 * * 6"

    def test_human_readable(self):
        from services import scheduler_service

        assert scheduler_service.describe("minute", n=30) == "每 30 分钟"
        assert scheduler_service.describe("daily", time="11:05") == "每天 11:05"


class TestEngineLogCapture:
    def test_engine_logs_mirrored_into_run(self, client, operator_token, fake_engine, db_session, caplog):
        """引擎日志经根 logger 镜像进 run 日志（FR-4.2 运行中日志含引擎内部进度）。"""
        import logging

        from engine_adapter.log_hub import capture_engine_logs

        run_id = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        with capture_engine_logs(run_id):
            logging.getLogger("crawl.engine").info("[CrawlInfo] crawl finished, found 3 sites")
        rows = client.get(f"/api/tasks/{run_id}/logs", headers=auth_header(operator_token)).json()["data"]["items"]
        messages = [r["message"] for r in rows]
        assert any("crawl finished" in m for m in messages), messages

    def test_single_probe_noise_filtered(self, client, operator_token):
        import logging

        from engine_adapter.log_hub import capture_engine_logs

        run_id = client.post(
            "/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)
        ).json()["data"]["id"]
        with capture_engine_logs(run_id):
            logging.getLogger("clash").info("[Check] node xxx delay ok")
            logging.getLogger("crawl.engine").info("[CrawlInfo] keep me")
        rows = client.get(f"/api/tasks/{run_id}/logs", headers=auth_header(operator_token)).json()["data"]["items"]
        messages = [r["message"] for r in rows]
        assert any("delay ok" in m for m in messages) is False
        assert any("keep me" in m for m in messages)


class TestRemotePublish:
    def test_gist_target_uses_push_machinery(self, client, admin_token, operator_token, db_session, tmp_path, monkeypatch):
        """远端目标经 subscribe/push 写入（非本地文件分支）。"""
        import sys
        from pathlib import Path

        from engine_adapter.registry import ensure_engine_on_path

        ensure_engine_on_path()
        import push as push_module

        calls = {}

        class FakeGist:
            def push_to(self, content, item, group="", retry=5, **kwargs):
                calls.setdefault("items", []).append({"file": item.filename, "gist": item.gist_id, "n": len(content)})
                return True

        monkeypatch.setattr(push_module, "get_instance", lambda storage: FakeGist())

        from models import CrawlRun, StorageTarget

        session = db_session
        target = StorageTarget(type="gist", name="gm", enable=True,
                               config={"gist_id": "6b08d288"}, token_ref="enc:xxx")
        session.add(target)
        session.flush()

        run = CrawlRun(run_uuid="pub-1", trigger="manual", mode="full", status="running")
        session.add(run)
        session.flush()

        # 准备两个产物文件
        art_dir = tmp_path / "arts"
        art_dir.mkdir()
        (art_dir / "clash.yaml").write_text("proxies: []", encoding="utf8")
        (art_dir / "singbox.json").write_text('{"outbounds":[]}', encoding="utf8")
        specs = [{"target": "clash", "path": str(art_dir / "clash.yaml"), "size": 12},
                 {"target": "singbox", "path": str(art_dir / "singbox.json"), "size": 17}]

        from engine_adapter.publisher import publish

        pending = publish(session, run.id, specs, [target.id])
        session.commit()
        assert pending == []
        assert [c["file"] for c in calls["items"]] == ["clash.yaml", "singbox.json"]
        assert calls["items"][0]["gist"] == "6b08d288"

    def test_empty_artifact_not_pushed(self, client, admin_token, db_session, tmp_path):
        from models import CrawlRun, StorageTarget

        from engine_adapter.publisher import publish

        session = db_session
        target = session.query(StorageTarget).filter_by(name="data-local").first()
        target.config = {"dir": str(tmp_path / "out"), "keep": 5}
        run = CrawlRun(run_uuid="pub-2", trigger="manual", mode="full", status="running")
        session.add(run)
        session.flush()
        empty = tmp_path / "v2ray.txt"
        empty.write_text("", encoding="utf8")
        specs = [{"target": "v2ray", "path": str(empty), "size": 0}]
        pending = publish(session, run.id, specs, [target.id])
        session.commit()
        assert pending == []
        assert not (tmp_path / "out" / "v2ray.txt").exists()  # 空产物不落盘


def _node_key(proxy: dict) -> str:
    return f"{proxy.get('server', '')}:{proxy.get('port', '')}:{proxy.get('type', '')}"


def _scripted_engine(subscriptions=(), fetch_map=None, alive_keys=None, loose=()):
    """确定性脚本引擎：crawl 返回给定订阅/散节点；fetch 按订阅映射产出节点；check 按 key 过滤存活。"""
    from engine_adapter.runner import CrawlOutcome

    class _Engine:
        def crawl(self, ctx):
            ctx.check_cancelled()
            return CrawlOutcome(subscriptions=list(subscriptions), loose=list(loose))

        def fetch(self, ctx, subscriptions, loose):
            ctx.check_cancelled()
            proxies = []
            for url in subscriptions:
                for proxy in (fetch_map or {}).get(url, []):
                    proxies.append({**proxy, "_kind": "sub", "_source_sub": url})
            for item in loose:
                if item.proxy:
                    proxies.append({**item.proxy, "_kind": "crawl", "_source": item.source})
            return proxies

        def check(self, ctx, proxies):
            ctx.check_cancelled()
            if alive_keys is None:
                return [dict(p) for p in proxies]
            return [dict(p) for p in proxies if _node_key(p) in alive_keys]

        def convert(self, ctx, alive):
            ctx.check_cancelled()
            return []

    return _Engine()


def _use_engine(engine):
    """注入脚本引擎并返回还原函数。"""
    from engine_adapter import runner as runner_module

    runner = runner_module.TaskRunner.instance()
    previous = runner.engine
    runner.engine = engine
    return lambda: setattr(runner, "engine", previous)


class TestVerifiedPersistence:
    def test_crawl_mode_persists_only_reachable_subscriptions(self, client, operator_token, db_session):
        """仅爬取：订阅级验证（可达性）通过才入订阅池；不可达的新订阅不入库。"""
        from models import Subscription

        restore = _use_engine(_scripted_engine(subscriptions=[
            ("https://ok.example.com/a", "PAGE", True),
            ("https://bad.example.com/b", "PAGE", False),
        ]))
        try:
            run_id = client.post("/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)).json()["data"]["id"]
            data = _wait_run(client, operator_token, run_id)
        finally:
            restore()
        assert data["status"] == "success"
        rows = db_session.query(Subscription).all()
        assert [r.url for r in rows] == ["https://ok.example.com/a"]
        assert rows[0].status == "alive" and rows[0].errors == 0

    def test_crawl_mode_does_not_persist_unverified_loose_nodes(self, client, operator_token, db_session):
        """仅爬取：散节点未经验活，不写入节点库。"""
        from engine_adapter.runner import LooseNode
        from models import Node

        restore = _use_engine(_scripted_engine(
            subscriptions=[("https://ok.example.com/a", "PAGE", True)],
            loose=[LooseNode(source="tg-a", proxy={"name": "n1", "type": "vless", "server": "s1.example.com", "port": 443})],
        ))
        try:
            run_id = client.post("/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)).json()["data"]["id"]
            _wait_run(client, operator_token, run_id)
        finally:
            restore()
        assert db_session.query(Node).count() == 0

    def test_full_mode_persists_only_verified_subscriptions_and_alive_nodes(self, client, operator_token, db_session, tmp_path):
        """爬取+聚合：仅「产出存活节点」的订阅入订阅结果；节点库整体替换为验活存活集。"""
        from models import Node, StorageTarget, Subscription

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        target.config = {"dir": str(tmp_path / "local"), "keep": 5}
        # 旧数据：上轮验活确认可用的订阅与节点
        db_session.add(Subscription(url="https://old.example.com/x", origin="PAGE", status="alive", errors=0, node_count=1))
        db_session.flush()
        run_old = __import__("models").CrawlRun(run_uuid="old-run", trigger="manual", mode="full", status="success", stage="done", params={}, stats={})
        db_session.add(run_old)
        db_session.flush()
        db_session.add_all([
            Node(run_id=run_old.id, name="old-sub-node", protocol="vless", server="old-sub.example.com", port=443,
                 kind="sub", source_sub="https://old.example.com/x", delay_ms=200, alive=True,
                 raw={"name": "old-sub-node", "type": "vless", "server": "old-sub.example.com", "port": 443}),
            Node(run_id=run_old.id, name="old-loose", protocol="vmess", server="old-loose.example.com", port=80,
                 kind="crawl", source="tg-a", delay_ms=300, alive=True,
                 raw={"name": "old-loose", "type": "vmess", "server": "old-loose.example.com", "port": 80}),
        ])
        db_session.commit()

        new_node = {"name": "new-1", "type": "vless", "server": "new1.example.com", "port": 443}
        dead_new_node = {"name": "new-dead", "type": "vmess", "server": "newdead.example.com", "port": 80}
        restore = _use_engine(_scripted_engine(
            subscriptions=[
                ("https://new.example.com/a", "PAGE", True),
                ("https://new.example.com/dead", "PAGE", False),
            ],
            fetch_map={
                "https://new.example.com/a": [new_node],
                "https://old.example.com/x": [{"name": "old-sub-node2", "type": "vless", "server": "old-sub2.example.com", "port": 443}],
            },
            # 仅新订阅的节点与旧散节点存活；旧订阅节点与新死节点均失效
            alive_keys={_node_key(new_node), _node_key({"server": "old-loose.example.com", "port": 80, "type": "vmess"})},
        ))
        try:
            run_id = client.post(
                "/api/tasks", json={"mode": "full", "bind_target_ids": [target.id]}, headers=auth_header(operator_token)
            ).json()["data"]["id"]
            data = _wait_run(client, operator_token, run_id)
        finally:
            restore()
        assert data["status"] == "success"
        assert data["stats"]["subs_usable"] == 1

        db_session.expire_all()
        subs = {s.url: s for s in db_session.query(Subscription).all()}
        assert subs["https://new.example.com/a"].status == "alive"
        assert subs["https://new.example.com/a"].node_count == 1
        assert "https://new.example.com/dead" not in subs, "不可达的新订阅不入库"
        # 旧订阅复核失败：失效计数 +1、节点数清零，容忍期内保留
        assert subs["https://old.example.com/x"].status == "dead"
        assert subs["https://old.example.com/x"].errors == 1
        assert subs["https://old.example.com/x"].node_count == 0

        nodes = {n.name: n for n in db_session.query(Node).all()}
        assert set(nodes) == {"new-1", "old-loose"}, "节点库仅保留验活存活节点"
        assert nodes["old-loose"].kind == "crawl" and nodes["old-loose"].source == "tg-a", "旧散节点复核后保留来源归属"
        assert nodes["new-1"].source_sub == "https://new.example.com/a"

    def test_old_pool_subscription_removed_at_max_fails(self, client, operator_token, db_session, tmp_path):
        """旧订阅连续复核失败达 max_fails 后从订阅池移除。"""
        from models import StorageTarget, Subscription

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        target.config = {"dir": str(tmp_path / "local"), "keep": 5}
        db_session.add(Subscription(url="https://dying.example.com/x", origin="PAGE", status="dead", errors=4))  # max_fails=5（种子默认）
        db_session.commit()

        restore = _use_engine(_scripted_engine(subscriptions=[], fetch_map={"https://dying.example.com/x": []}, alive_keys=set()))
        try:
            run_id = client.post(
                "/api/tasks", json={"mode": "aggregate", "bind_target_ids": [target.id]}, headers=auth_header(operator_token)
            ).json()["data"]["id"]
            _wait_run(client, operator_token, run_id)
        finally:
            restore()
        db_session.expire_all()
        assert db_session.query(Subscription).filter_by(url="https://dying.example.com/x").first() is None

    def test_proxy_scope_applies_during_run_and_restores(self, client, operator_token, db_session, monkeypatch):
        """爬取参数启用本地代理时：运行期间注入代理 env（引擎全链路经代理回退直连），结束后恢复。"""
        import os

        from engine_adapter.registry import ensure_engine_on_path

        ensure_engine_on_path()
        import httpclient

        from models import Setting

        setting = db_session.get(Setting, "crawl")
        setting.value = {**dict(setting.value or {}), "proxy": {"enable": True, "address": "http://127.0.0.1:7897", "test_url": "https://api.github.com/zen"}}
        db_session.commit()

        calls = {}
        seen_env = {}

        def fake_configure(enable, address, test_url, context=None):
            calls["args"] = (enable, address, test_url)
            os.environ["HTTP_PROXY"] = address
            return address

        monkeypatch.setattr(httpclient, "configure_proxy", fake_configure)

        class EnvProbeEngine(_scripted_engine().__class__):
            def crawl(self, ctx):
                seen_env["HTTP_PROXY"] = os.environ.get("HTTP_PROXY")
                return super().crawl(ctx)

        restore = _use_engine(EnvProbeEngine())
        before = os.environ.get("HTTP_PROXY")
        try:
            run_id = client.post("/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)).json()["data"]["id"]
            _wait_run(client, operator_token, run_id)
        finally:
            restore()
        assert calls["args"][0] is True and calls["args"][1] == "http://127.0.0.1:7897"
        assert seen_env["HTTP_PROXY"] == "http://127.0.0.1:7897", "运行期间代理 env 已注入"
        assert os.environ.get("HTTP_PROXY") == before, "运行结束后代理 env 已恢复"

    def test_proxy_scope_skipped_when_disabled(self, client, operator_token, db_session, monkeypatch):
        """代理未启用时不调用 configure_proxy。"""
        from engine_adapter.registry import ensure_engine_on_path

        ensure_engine_on_path()
        import httpclient

        from models import Setting

        setting = db_session.get(Setting, "crawl")
        setting.value = {**dict(setting.value or {}), "proxy": {"enable": False, "address": "http://127.0.0.1:7897"}}
        db_session.commit()

        called = []
        monkeypatch.setattr(httpclient, "configure_proxy", lambda *a, **kw: called.append(1) or "")
        restore = _use_engine(_scripted_engine())
        try:
            run_id = client.post("/api/tasks", json={"mode": "crawl"}, headers=auth_header(operator_token)).json()["data"]["id"]
            _wait_run(client, operator_token, run_id)
        finally:
            restore()
        assert not called


class TestPersistRobustness:
    def test_batch_dedup_same_url_with_reachable_priority(self, db_session):
        """同一 url 在一批内重复出现（跨源命中）：去重且可达状态优先，不触发唯一约束。"""
        from engine_adapter.runner import _persist_validated_subscriptions
        from models import Subscription

        _persist_validated_subscriptions(
            db_session,
            [
                ("https://dup.example.com/a", "TELEGRAM", False),
                ("https://dup.example.com/a", "GITHUB", True),
            ],
        )
        rows = db_session.query(Subscription).filter_by(url="https://dup.example.com/a").all()
        assert len(rows) == 1
        assert rows[0].status == "alive"
        assert rows[0].errors == 0

    def test_safe_execute_marks_failed_even_if_logging_fails(self, db_session):
        """异常路径健壮性：即使日志写入失败，run 也必须落终态、锁必须释放（曾卡 running）。"""
        from unittest.mock import patch

        from engine_adapter.runner import TaskRunner
        from models import CrawlRun

        run = TaskRunner.instance()
        session = db_session
        run.create(session, mode="crawl", params={}, source_ids=[], bind_target_ids=[], actor_id=None)
        # 直接驱动 _safe_execute：_execute 抛错 + log 也抛错，仍应标记 failed 并释放锁
        target = session.query(CrawlRun).order_by(CrawlRun.id.desc()).first()

        def boom(_self, _s, _r):
            raise RuntimeError("engine exploded")

        with patch.object(type(run), "_execute", boom), \
             patch("engine_adapter.log_hub.log", side_effect=RuntimeError("log also broken")):
            run._safe_execute(target.id)
        session.expire_all()
        refreshed = session.get(CrawlRun, target.id)
        assert refreshed.status == "failed"
        assert "engine exploded" in (refreshed.error or "")
        assert run.running_id is None
