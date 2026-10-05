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
