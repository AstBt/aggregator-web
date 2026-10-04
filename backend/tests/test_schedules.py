# -*- coding: utf-8 -*-
"""定时任务 API 与调度执行器测试（FR-4.8 / A15）。"""

from __future__ import annotations

import time

import pytest

from conftest import auth_header


@pytest.fixture()
def operator_token(client, admin_token) -> str:
    client.post(
        "/api/users",
        json={"username": "operator1", "password": "pass1234", "role": "operator"},
        headers=auth_header(admin_token),
    )
    return client.post(
        "/api/auth/login", json={"username": "operator1", "password": "pass1234"}
    ).json()["data"]["accessToken"]


def _make_target(client, admin_token, db_session, tmp_path):
    from models import StorageTarget

    target = db_session.query(StorageTarget).filter_by(name="data-local").first()
    target.config = {"dir": str(tmp_path / "local"), "keep": 5}
    db_session.commit()
    return target.id


class TestSchedulesApi:
    def test_create_minute_schedule_translates_cron(self, client, operator_token):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "每分钟",
                "kind": "minute",
                "n": 1,
                "mode": "crawl",
                "params": {"num_threads": 8},
                "bind_target_ids": [],
                "enable": True,
            },
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["cron"] == "*/1 * * * *"
        assert resp.json()["data"]["mode"] == "crawl"

    def test_create_daily_schedule(self, client, operator_token):
        resp = client.post(
            "/api/schedules",
            json={"name": "每天", "kind": "daily", "time": "11:05", "mode": "full", "bind_target_ids": [1]},
            headers=auth_header(operator_token),
        )
        assert resp.json()["data"]["cron"] == "5 11 * * *"

    def test_aggregate_requires_binding(self, client, operator_token):
        resp = client.post(
            "/api/schedules",
            json={"name": "回测定时", "kind": "hour", "n": 6, "mode": "aggregate", "bind_target_ids": []},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400
        assert "绑定" in resp.json()["message"]

    def test_invalid_schedule_params(self, client, operator_token):
        resp = client.post(
            "/api/schedules",
            json={"name": "bad", "kind": "minute", "time": "99:99", "mode": "crawl"},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400

    def test_list_and_toggle_and_delete(self, client, operator_token):
        sid = client.post(
            "/api/schedules",
            json={"name": "t1", "kind": "hour", "n": 2, "mode": "crawl"},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        listing = client.get("/api/schedules", headers=auth_header(operator_token)).json()["data"]
        assert listing["total"] == 1
        toggled = client.post(f"/api/schedules/{sid}/toggle", headers=auth_header(operator_token)).json()["data"]
        assert toggled["enable"] is False
        assert client.delete(f"/api/schedules/{sid}", headers=auth_header(operator_token)).status_code == 200
        assert client.get("/api/schedules", headers=auth_header(operator_token)).json()["data"]["total"] == 0

    def test_viewer_readonly(self, client, admin_token, operator_token):
        client.post(
            "/api/users",
            json={"username": "viewer8", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer8", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.get("/api/schedules", headers=auth_header(viewer)).status_code == 200
        assert (
            client.post(
                "/api/schedules", json={"name": "x", "kind": "minute", "mode": "crawl"}, headers=auth_header(viewer)
            ).status_code
            == 403
        )


class TestSchedulerHub:
    def test_fire_creates_schedule_run(self, client, operator_token, fake_engine, db_session, tmp_path):
        """到点触发：为启用 schedule 生成 trigger=schedule 的 run（A15）。"""
        from engine_adapter.scheduler import SchedulerHub
        from models import StorageTarget

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        target.config = {"dir": str(tmp_path / "local"), "keep": 5}
        db_session.commit()
        sid = client.post(
            "/api/schedules",
            json={"name": "每分钟", "kind": "minute", "n": 1, "mode": "crawl", "params": {"num_threads": 4}},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]

        hub = SchedulerHub()
        run = hub.fire(sid)
        assert run is not None
        assert run.trigger == "schedule"
        assert run.mode == "crawl"

        import time as _t

        deadline = _t.time() + 10
        while _t.time() < deadline:
            db_session.expire_all()
            data = client.get(f"/api/tasks/{run.id}", headers=auth_header(operator_token)).json()["data"]
            if data["status"] in ("success", "failed", "cancelled", "partial-success"):
                break
            _t.sleep(0.2)
        assert data["status"] == "success"
        db_session.expire_all()
        assert hub.schedule(sid).last_run_at is not None

    def test_fire_disabled_schedule_noop(self, client, operator_token):
        from engine_adapter.scheduler import SchedulerHub

        sid = client.post(
            "/api/schedules",
            json={"name": "off", "kind": "minute", "n": 1, "mode": "crawl"},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        client.post(f"/api/schedules/{sid}/toggle", headers=auth_header(operator_token))
        hub = SchedulerHub()
        assert hub.fire(sid) is None

    def test_fire_when_runner_busy_skips(self, client, operator_token, fake_engine):
        """执行器被占用时跳过本轮并记录原因（避免并发写）。"""
        from engine_adapter import runner as runner_module
        from engine_adapter.scheduler import SchedulerHub

        class HoldEngine(runner_module.HermeticEngine):
            def crawl(self, ctx):
                import time as _t

                for _ in range(50):
                    if ctx.cancelled:
                        raise runner_module.RunCancelled()
                    _t.sleep(0.1)
                return super().crawl(ctx)

        runner_module.TaskRunner.instance().engine = HoldEngine(subscriptions=[], proxies=[])
        sid = client.post(
            "/api/schedules",
            json={"name": "busy", "kind": "minute", "n": 1, "mode": "crawl"},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        runner_module.TaskRunner.instance().create(
            __import__("db").SessionLocal(), mode="crawl", params={}, source_ids=[], bind_target_ids=[], actor_id=None
        )
        runner_module.TaskRunner.instance().start(1)
        time.sleep(0.3)
        hub = SchedulerHub()
        assert hub.fire(sid) is None  # 忙碌跳过
        reason = hub.schedule(sid).disabled_reason
        runner_module.TaskRunner.instance().cancel(1)
        assert reason and "仍在运行" in reason
