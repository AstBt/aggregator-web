# -*- coding: utf-8 -*-
"""结果页 API 测试（FR-5.3~5.9, A12/A13）。"""

from __future__ import annotations

import base64
import json

import pytest

from conftest import auth_header


@pytest.fixture()
def seeded_run(client, admin_token, operator_token, db_session, tmp_path):
    """直接播种一轮 full 运行数据（节点/订阅/产物），绕过引擎。"""
    from datetime import datetime

    from models import Artifact, CrawlRun, Node, StorageTarget, Subscription

    target = db_session.query(StorageTarget).filter_by(name="data-local").first()
    target.config = {"dir": str(tmp_path / "local"), "keep": 5}
    run = CrawlRun(
        run_uuid="seed-run-0001",
        trigger="manual",
        mode="full",
        status="success",
        stage="done",
        params={"bind_target_ids": [target.id]},
        stats={"nodes_alive": 4, "subs_alive": 2},
        started_at=datetime.now(),
        finished_at=datetime.now(),
        duration_ms=1200,
    )
    db_session.add(run)
    db_session.flush()
    subs = [
        Subscription(url="https://a.example.com/link/abc?sub=1", origin="TELEGRAM", status="alive", errors=0),
        Subscription(url="https://b.example.com/sub", origin="PAGE", status="alive", errors=0),
        Subscription(url="https://dead.example.com/x", origin="GIST", status="dead", errors=6),
    ]
    db_session.add_all(subs)
    nodes = [
        Node(run_id=run.id, name="🚀 香港01", protocol="vless", server="hk01.example.com", port=443,
             source_sub=subs[0].url, delay_ms=180, region="香港", residential=False, alive=True,
             raw={"type": "vless", "uuid": "e5f3-a91c", "network": "ws", "tls": True}),
        Node(run_id=run.id, name="🚀 新加坡02", protocol="vmess", server="sg02.example.net", port=80,
             source_sub=subs[0].url, delay_ms=460, region="新加坡", residential=False, alive=True,
             raw={"type": "vmess", "uuid": "7b2c-11f0", "alterId": 0}),
        Node(run_id=run.id, name="🚀 香港04", protocol="hysteria2", server="hk04.example.io", port=36712,
             source_sub=subs[1].url, delay_ms=167, region="香港", residential=True, alive=True,
             raw={"type": "hysteria2", "password": "s3cret", "sni": "hk04.example.io"}),
        Node(run_id=run.id, name="🚀 美国05", protocol="ss", server="us05.example.com", port=8388,
             source_sub=subs[1].url, delay_ms=920, region="美国", residential=True, alive=True,
             raw={"type": "ss", "cipher": "aes-128-gcm", "password": "pw"}),
    ]
    db_session.add_all(nodes)
    db_session.add(Artifact(run_id=run.id, target="clash", path=str(tmp_path / "local" / "clash.yaml"), size=1024))
    db_session.commit()
    return {"run_id": run.id, "target_id": target.id, "node_ids": [n.id for n in nodes]}


class TestSubscriptions:
    def test_list_and_filter(self, client, operator_token, seeded_run):
        resp = client.get("/api/subscriptions?status=alive", headers=auth_header(operator_token)).json()["data"]
        assert resp["total"] == 2
        dead = client.get("/api/subscriptions?status=dead", headers=auth_header(operator_token)).json()["data"]
        assert dead["total"] == 1
        search = client.get("/api/subscriptions?keyword=a.example", headers=auth_header(operator_token)).json()["data"]
        assert search["total"] == 1

    def test_detail_with_contributed_nodes(self, client, operator_token, seeded_run):
        item = client.get("/api/subscriptions", headers=auth_header(operator_token)).json()["data"]["items"][0]
        detail = client.get(f"/api/subscriptions/{item['id']}", headers=auth_header(operator_token)).json()["data"]
        assert detail["url"] == item["url"]
        assert detail["contributed_nodes"] >= 1


class TestNodes:
    def test_filter_by_protocol_and_alive(self, client, operator_token, seeded_run):
        vless = client.get("/api/nodes?protocol=vless", headers=auth_header(operator_token)).json()["data"]
        assert vless["total"] == 1
        assert vless["items"][0]["server"] == "hk01.example.com"

    def test_filter_delay_range(self, client, operator_token, seeded_run):
        fast = client.get("/api/nodes?max_delay=300", headers=auth_header(operator_token)).json()["data"]
        assert fast["total"] == 2
        slow = client.get("/api/nodes?min_delay=900", headers=auth_header(operator_token)).json()["data"]
        assert slow["total"] == 1

    def test_keyword_search(self, client, operator_token, seeded_run):
        res = client.get("/api/nodes?keyword=香港04", headers=auth_header(operator_token)).json()["data"]
        assert res["total"] == 1 and res["items"][0]["residential"] is True

    def test_no_group_field(self, client, operator_token, seeded_run):
        """v2.0 起无分组概念（FR-5.4）。"""
        item = client.get("/api/nodes", headers=auth_header(operator_token)).json()["data"]["items"][0]
        assert "group" not in item

    def test_node_detail_raw(self, client, operator_token, seeded_run):
        item = client.get("/api/nodes?protocol=ss", headers=auth_header(operator_token)).json()["data"]["items"][0]
        detail = client.get(f"/api/nodes/{item['id']}", headers=auth_header(operator_token)).json()["data"]
        assert detail["raw"]["cipher"] == "aes-128-gcm"


class TestExport:
    def test_clash_export_yaml(self, client, operator_token, seeded_run):
        resp = client.post(
            "/api/nodes/export",
            json={"target": "clash", "only_alive": True},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["target"] == "clash" and data["count"] == 4
        assert "proxies:" in data["content"]
        assert "🚀 香港01" in data["content"]

    def test_v2ray_export_base64(self, client, operator_token, seeded_run):
        resp = client.post(
            "/api/nodes/export",
            json={"target": "v2ray", "only_alive": True},
            headers=auth_header(operator_token),
        ).json()["data"]
        decoded = base64.b64decode(resp["content"]).decode()
        assert decoded.count("://") == 4

    def test_singbox_export_json(self, client, operator_token, seeded_run):
        resp = client.post(
            "/api/nodes/export",
            json={"target": "singbox", "only_alive": True},
            headers=auth_header(operator_token),
        ).json()["data"]
        parsed = json.loads(resp["content"])
        node_outbounds = [o for o in parsed["outbounds"] if o["type"] != "direct"]
        assert len(node_outbounds) == 4
        assert {o["tag"] for o in node_outbounds} >= {"🚀 香港01", "🚀 香港04"}

    def test_export_default_only_alive(self, client, operator_token, seeded_run, db_session):
        from models import Node

        db_session.add(Node(run_id=seeded_run["run_id"], name="☠️ 死节点", protocol="vless",
                            server="dead.example.com", port=443, alive=False, raw={"type": "vless"}))
        db_session.commit()
        default = client.post(
            "/api/nodes/export", json={"target": "clash"}, headers=auth_header(operator_token)
        ).json()["data"]
        assert default["count"] == 4  # 死节点默认排除
        withdead = client.post(
            "/api/nodes/export",
            json={"target": "clash", "only_alive": False},
            headers=auth_header(operator_token),
        ).json()["data"]
        assert withdead["count"] == 5

    def test_unsupported_target_400(self, client, operator_token, seeded_run):
        resp = client.post(
            "/api/nodes/export", json={"target": "surge"}, headers=auth_header(operator_token)
        )
        assert resp.status_code == 400

    def test_export_limit(self, client, operator_token, seeded_run, db_session):
        from models import Setting

        db_session.merge(Setting(key="export", value={"node_limit": 2, "emoji": True}))
        db_session.commit()
        resp = client.post(
            "/api/nodes/export", json={"target": "clash"}, headers=auth_header(operator_token)
        )
        assert resp.status_code == 400
        assert "上限" in resp.json()["message"]


class TestCsvExport:
    def test_nodes_csv(self, client, operator_token, seeded_run):
        resp = client.get("/api/export/nodes.csv", headers=auth_header(operator_token))
        assert resp.status_code == 200
        assert "🚀 香港01" in resp.text and "protocol" in resp.text
