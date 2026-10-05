# -*- coding: utf-8 -*-
"""订阅/节点状态测试 API 测试（结果板块批量测试）。"""

from __future__ import annotations

import time

import pytest

from conftest import auth_header


@pytest.fixture()
def seeded(client, admin_token, operator_token, db_session):
    from datetime import datetime

    from models import CrawlRun, Node, StorageTarget, Subscription

    target = db_session.query(StorageTarget).filter_by(name="data-local").first()
    run = CrawlRun(run_uuid="test-seed", trigger="manual", mode="full", status="success", stage="done",
                   params={}, stats={}, started_at=datetime.now(), finished_at=datetime.now(), duration_ms=100)
    db_session.add(run)
    db_session.flush()
    # 订阅：一个存活一个失效
    db_session.add_all([
        Subscription(url="https://a.example.com/link/abc?sub=1", origin="TELEGRAM", status="alive", errors=0),
        Subscription(url="https://dead.example.com/x", origin="GIST", status="dead", errors=2),
    ])
    # 散节点（crawl）与订阅节点（sub）
    db_session.add_all([
        Node(run_id=run.id, name="🚀 香港01", protocol="vless", server="hk01.example.com", port=443,
             kind="crawl", source="oneclickvpnkeys", delay_ms=180, region="香港", alive=True, raw={"type": "vless"}),
        Node(run_id=run.id, name="🚀 新加坡02", protocol="vmess", server="sg02.example.net", port=80,
             kind="crawl", source="oneclickvpnkeys", delay_ms=460, region="新加坡", alive=True, raw={"type": "vmess"}),
        Node(run_id=run.id, name="sub-node-01", protocol="vless", server="sub1.example.com", port=443,
             kind="sub", source_sub="https://a.example.com/link/abc?sub=1", delay_ms=None, alive=True, raw={"type": "vless"}),
    ])
    db_session.commit()
    return {"run_id": run.id}


class TestSubscriptionTesting:
    def test_test_selected_subscriptions(self, client, operator_token, seeded, monkeypatch):
        from services import test_service

        monkeypatch.setattr(test_service, "_probe_subscription", lambda url: (True, 12))
        resp = client.post("/api/subscriptions/test", json={"ids": [1]}, headers=auth_header(operator_token))
        assert resp.status_code == 200, resp.text
        job = resp.json()["data"]
        assert job["total"] == 1
        _wait_job(client, operator_token, job["job_id"])
        detail = client.get("/api/subscriptions/1", headers=auth_header(operator_token)).json()["data"]
        assert detail["status"] == "alive"
        assert detail["node_count"] == 12

    def test_test_all_when_no_ids(self, client, operator_token, seeded, monkeypatch):
        from services import test_service

        def fake(url):
            return ("dead" not in url, 3)

        monkeypatch.setattr(test_service, "_probe_subscription", fake)
        resp = client.post("/api/subscriptions/test", json={}, headers=auth_header(operator_token))
        job = resp.json()["data"]
        assert job["total"] == 2
        _wait_job(client, operator_token, job["job_id"])
        a = client.get("/api/subscriptions/1", headers=auth_header(operator_token)).json()["data"]
        b = client.get("/api/subscriptions/2", headers=auth_header(operator_token)).json()["data"]
        assert a["status"] == "alive" and a["node_count"] == 3
        assert b["status"] == "dead" and b["errors"] >= 1

    def test_testing_status_visible_during_run(self, client, operator_token, seeded, monkeypatch):
        from services import test_service

        def slow(url):
            time.sleep(1.2)
            return (True, 5)

        monkeypatch.setattr(test_service, "_probe_subscription", slow)
        client.post("/api/subscriptions/test", json={"ids": [1]}, headers=auth_header(operator_token))
        mid = client.get("/api/subscriptions/1", headers=auth_header(operator_token)).json()["data"]
        assert mid["status"] == "testing"

    def test_viewer_cannot_test(self, client, admin_token, operator_token, seeded):
        client.post(
            "/api/users",
            json={"username": "viewer7", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer7", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.post("/api/subscriptions/test", json={}, headers=auth_header(viewer)).status_code == 403


class TestNodeTesting:
    def test_test_selected_nodes_updates_status(self, client, operator_token, seeded, monkeypatch):
        from services import test_service

        def fake_check(proxies, **kwargs):
            from services.test_service import _node_key

            return {_node_key(p): (111 if p.get("type") == "vless" else 222) for p in proxies}

        monkeypatch.setattr(test_service, "_check_alive", fake_check)
        resp = client.post("/api/nodes/test", json={"ids": [1, 2], "locate": False}, headers=auth_header(operator_token))
        assert resp.status_code == 200
        job = resp.json()["data"]
        assert job["total"] == 2
        _wait_job(client, operator_token, job["job_id"])
        nodes = client.get("/api/nodes?kind=crawl", headers=auth_header(operator_token)).json()["data"]["items"]
        by_name = {n["name"]: n for n in nodes}
        assert by_name["🚀 香港01"]["delay_ms"] == 111
        assert by_name["🚀 新加坡02"]["delay_ms"] == 222

    def test_test_all_crawl_nodes_when_no_ids(self, client, operator_token, seeded, monkeypatch):
        from services import test_service

        def fake_check(proxies, **kwargs):
            from services.test_service import _node_key

            return {_node_key(p): 333 for p in proxies}

        monkeypatch.setattr(test_service, "_check_alive", fake_check)
        resp = client.post("/api/nodes/test", json={"locate": False}, headers=auth_header(operator_token))
        job = resp.json()["data"]
        assert job["total"] == 2  # 默认只测散节点（kind=crawl）
        _wait_job(client, operator_token, job["job_id"])
        nodes = client.get("/api/nodes?kind=crawl", headers=auth_header(operator_token)).json()["data"]["items"]
        assert all(n["delay_ms"] == 333 for n in nodes)

    def test_sub_nodes_not_in_crawl_list(self, client, operator_token, seeded):
        """节点浏览默认只含散节点；订阅节点只在订阅详情出现（两块独立）。"""
        crawl = client.get("/api/nodes?kind=crawl", headers=auth_header(operator_token)).json()["data"]
        assert crawl["total"] == 2
        assert all(n["kind"] == "crawl" for n in crawl["items"])
        assert {n["source"] for n in crawl["items"]} == {"oneclickvpnkeys"}

        sub_nodes = client.get(
            "/api/subscriptions/1/nodes", headers=auth_header(operator_token)
        ).json()["data"]
        assert sub_nodes["total"] == 1
        assert sub_nodes["items"][0]["kind"] == "sub"

    def test_viewer_cannot_test_nodes(self, client, admin_token, operator_token, seeded):
        client.post(
            "/api/users",
            json={"username": "viewer6", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer6", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.post("/api/nodes/test", json={}, headers=auth_header(viewer)).status_code == 403


def _wait_job(client, token, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = client.get("/api/test-jobs", headers=auth_header(token)).json()["data"]["items"]
        if jobs and all(j["status"] in ("success", "failed") for j in jobs):
            return jobs
        time.sleep(0.3)
    raise AssertionError("test job 未在超时前完成")
