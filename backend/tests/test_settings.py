# -*- coding: utf-8 -*-
"""爬取/验活参数与代理测试 API 测试（FR-3.9~3.16, A6/A7）。"""

from __future__ import annotations

import pytest

from conftest import auth_header


class TestCrawlParams:
    def test_defaults_and_update(self, client, operator_token):
        resp = client.get("/api/settings/crawl", headers=auth_header(operator_token))
        assert resp.json()["data"]["max_fails"] == 5

        resp = client.put(
            "/api/settings/crawl",
            json={"max_fails": 3, "exclude": "(过期|失效)"},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 200
        again = client.get("/api/settings/crawl", headers=auth_header(operator_token))
        assert again.json()["data"]["max_fails"] == 3
        assert again.json()["data"]["exclude"] == "(过期|失效)"

    def test_no_default_task_params_or_persist(self, client, operator_token):
        """v2.1 起删除默认任务参数/持久化绑定（FR-3.9 说明）。"""
        resp = client.get("/api/settings/crawl", headers=auth_header(operator_token))
        data = resp.json()["data"]
        assert "task_defaults" not in data and "persist" not in data

    def test_proxy_toggle_and_test(self, client, operator_token, monkeypatch):
        from services import settings_service

        monkeypatch.setattr(
            settings_service, "probe_via_proxy", lambda *a, **k: {"ok": True, "status": 200, "cost_ms": 95}
        )
        resp = client.put(
            "/api/settings/crawl",
            json={"proxy": {"enable": True, "address": "http://127.0.0.1:7897"}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 200
        resp = client.post("/api/settings/crawl/proxy/test", headers=auth_header(operator_token))
        assert resp.json()["data"]["ok"] is True
        assert resp.json()["data"]["cost_ms"] == 95

    def test_viewer_readonly(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "viewer2", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post(
            "/api/auth/login", json={"username": "viewer2", "password": "pass1234"}
        ).json()["data"]["accessToken"]
        assert client.get("/api/settings/crawl", headers=auth_header(viewer)).status_code == 200
        assert client.put(
            "/api/settings/crawl", json={"max_fails": 1}, headers=auth_header(viewer)
        ).status_code == 403


class TestAliveParams:
    def test_defaults_and_update(self, client, operator_token):
        resp = client.get("/api/settings/alive", headers=auth_header(operator_token))
        assert resp.json()["data"]["max_delay"] == 5000
        resp = client.put(
            "/api/settings/alive",
            json={"timeout": 4000, "max_delay": 3000, "num_threads": 32},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 200
        again = client.get("/api/settings/alive", headers=auth_header(operator_token)).json()["data"]
        assert again["timeout"] == 4000 and again["max_delay"] == 3000 and again["num_threads"] == 32

    def test_no_skip_alive_switch(self, client, operator_token):
        """验活是回测/full 既定步骤，无全局跳过开关（FR-3.16）。"""
        data = client.get("/api/settings/alive", headers=auth_header(operator_token)).json()["data"]
        assert "skip" not in data

    def test_test_url_list_management(self, client, operator_token):
        # 添加
        resp = client.post(
            "/api/settings/alive/test-urls",
            json={"url": "https://example.com/generate_204"},
            headers=auth_header(operator_token),
        )
        urls = resp.json()["data"]
        assert "https://example.com/generate_204" in urls
        # 非法地址拒绝
        bad = client.post(
            "/api/settings/alive/test-urls", json={"url": "not-a-url"}, headers=auth_header(operator_token)
        )
        assert bad.status_code == 400
        # 生效项单选 + 不允许删光
        all_urls = client.get("/api/settings/alive", headers=auth_header(operator_token)).json()["data"]["test_urls"]
        client.put(
            "/api/settings/alive",
            json={"test_urls": ["https://cp.cloudflare.com"], "primary_test_url": "https://cp.cloudflare.com"},
            headers=auth_header(operator_token),
        )
        data = client.get("/api/settings/alive", headers=auth_header(operator_token)).json()["data"]
        assert data["primary_test_url"] == "https://cp.cloudflare.com"
        assert all(u.startswith("http") for u in all_urls)
        empty = client.put(
            "/api/settings/alive", json={"test_urls": []}, headers=auth_header(operator_token)
        )
        assert empty.status_code == 400

    def test_url_connectivity_uses_proxy_when_enabled(self, client, operator_token, monkeypatch):
        """页面连通性测试经本地代理；实际节点验活直连（FR-3.14a）。"""
        from services import settings_service

        calls = {}
        def fake_probe(url, proxy=None):
            calls["url"] = url
            calls["proxy"] = proxy
            return {"ok": True, "status": 204, "cost_ms": 88}

        monkeypatch.setattr(settings_service, "probe_url", fake_probe)
        client.put(
            "/api/settings/crawl",
            json={"proxy": {"enable": True, "address": "http://127.0.0.1:7897"}},
            headers=auth_header(operator_token),
        )
        resp = client.post(
            "/api/settings/alive/test-url?url=https://www.google.com/generate_204",
            headers=auth_header(operator_token),
        )
        assert resp.json()["data"]["ok"] is True
        assert calls["proxy"] == "http://127.0.0.1:7897"

    def test_liveness_path_is_node_direct(self, client, operator_token):
        """语义固化：验活探测不经过本地代理（文档断言）。"""
        from services import settings_service

        assert settings_service.liveness_uses_proxy() is False
