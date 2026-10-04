# -*- coding: utf-8 -*-
"""仪表盘 API 测试（FR-2.1~2.7, A3）。"""

from __future__ import annotations

from datetime import datetime

import pytest

from conftest import auth_header


@pytest.fixture()
def seeded(client, admin_token, db_session):
    from models import CrawlRun, Node, StorageTarget, Subscription

    db_session.add_all(
        [
            Subscription(url="https://a.example.com/x", origin="TELEGRAM", status="alive"),
            Subscription(url="https://b.example.com/y", origin="PAGE", status="alive"),
            Subscription(url="https://c.example.com/z", origin="GIST", status="dead", errors=5),
        ]
    )
    run = CrawlRun(run_uuid="dash-1", trigger="manual", mode="full", status="success", stage="done",
                   stats={"nodes_alive": 5}, started_at=datetime.now(), finished_at=datetime.now(), duration_ms=900)
    db_session.add(run)
    db_session.flush()
    db_session.add_all(
        [
            Node(run_id=run.id, name="n1", protocol="vless", server="s1", port=443, delay_ms=120, region="香港",
                 residential=False, alive=True, raw={}),
            Node(run_id=run.id, name="n2", protocol="vmess", server="s2", port=80, delay_ms=500, region="美国",
                 residential=False, alive=True, raw={}),
            Node(run_id=run.id, name="n3", protocol="hysteria2", server="s3", port=443, delay_ms=980, region="香港",
                 residential=True, alive=True, raw={}),
        ]
    )
    db_session.query(StorageTarget).filter_by(name="data-local").first().last_write_ok = True
    db_session.commit()


class TestDashboard:
    def test_overview_metrics(self, client, admin_token, seeded):
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        assert data["subs_alive"] == 2
        assert data["nodes_alive"] == 3
        assert data["recent_runs"][0]["mode"] == "full"

    def test_protocol_distribution(self, client, admin_token, seeded):
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        dist = {d["protocol"]: d["count"] for d in data["protocol_distribution"]}
        assert dist == {"vless": 1, "vmess": 1, "hysteria2": 1}

    def test_delay_buckets(self, client, admin_token, seeded):
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        buckets = {b["label"]: b["count"] for b in data["delay_buckets"]}
        assert buckets["<300ms"] == 1 and buckets["300-800ms"] == 1 and buckets[">800ms"] == 1

    def test_region_top(self, client, admin_token, seeded):
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        regions = {r["region"]: r["count"] for r in data["region_top"]}
        assert regions.get("香港") == 2

    def test_storage_status(self, client, admin_token, seeded):
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        assert data["storage_targets_enabled"] >= 1
        assert isinstance(data["storage_status"], list)

    def test_source_health(self, client, admin_token, operator_token, seeded):
        client.post(
            "/api/sources",
            json={"type": "telegram", "name": "oneclickvpnkeys", "config": {"pages": 5}},
            headers=auth_header(operator_token),
        )
        data = client.get("/api/dashboard/overview", headers=auth_header(admin_token)).json()["data"]
        assert any(s["type"] == "telegram" for s in data["source_health"])

    def test_viewer_can_read(self, client, admin_token, seeded):
        client.post(
            "/api/users",
            json={"username": "viewer9", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer9", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.get("/api/dashboard/overview", headers=auth_header(viewer)).status_code == 200
