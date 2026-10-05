# -*- coding: utf-8 -*-
"""爬取源 API 测试（FR-3.1~3.8, A4/A5）。"""

from __future__ import annotations

import pytest

from conftest import auth_header


@pytest.fixture()
def operator_token(client, admin_token) -> str:
    client.post(
        "/api/users",
        json={"username": "operator1", "password": "pass1234", "role": "operator"},
        headers=auth_header(admin_token),
    )
    resp = client.post("/api/auth/login", json={"username": "operator1", "password": "pass1234"})
    return resp.json()["data"]["accessToken"]


class TestSourceCrud:
    def test_create_and_list(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "telegram", "name": "oneclickvpnkeys", "config": {"pages": 5}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201, resp.text
        listing = client.get("/api/sources", headers=auth_header(operator_token))
        assert listing.json()["data"]["total"] == 1
        assert listing.json()["data"]["items"][0]["name"] == "oneclickvpnkeys"

    def test_viewer_cannot_create(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "viewer1", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        viewer = client.post("/api/auth/login", json={"username": "viewer1", "password": "pass1234"}).json()[
            "data"
        ]["accessToken"]
        resp = client.post(
            "/api/sources",
            json={"type": "telegram", "name": "ch", "config": {}},
            headers=auth_header(viewer),
        )
        assert resp.status_code == 403

    def test_duplicate_name_409(self, client, operator_token):
        for _ in range(2):
            resp = client.post(
                "/api/sources",
                json={"type": "telegram", "name": "dup", "config": {}},
                headers=auth_header(operator_token),
            )
        assert resp.status_code == 409

    def test_toggle_enable(self, client, operator_token):
        sid = client.post(
            "/api/sources",
            json={"type": "gist", "name": "g1", "config": {"token": "ghp_fake", "max_gists": 50}},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        resp = client.post(f"/api/sources/{sid}/toggle", headers=auth_header(operator_token))
        assert resp.json()["data"]["enable"] is False
        listing = client.get("/api/sources?enable=false", headers=auth_header(operator_token))
        assert listing.json()["data"]["total"] == 1

    def test_delete_keeps_history(self, client, operator_token):
        sid = client.post(
            "/api/sources",
            json={"type": "page", "name": "p1", "config": {"url": ["https://a.example.com"]}},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        assert client.delete(f"/api/sources/{sid}", headers=auth_header(operator_token)).status_code == 200
        assert client.get("/api/sources", headers=auth_header(operator_token)).json()["data"]["total"] == 0


class TestSourceValidation:
    def test_invalid_regex_rejected(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "telegram", "name": "bad", "config": {"include": "[unclosed"}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400
        assert "包含正则" in resp.json()["message"]

    def test_page_requires_url(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "page", "name": "p2", "config": {}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400

    def test_paged_requires_placeholder_and_range(self, client, operator_token):
        base = {"type": "page", "name": "p3", "config": {"url": ["https://a.example.com/{page}"]}}
        bad = dict(base)
        bad["config"] = {"url": ["https://a.com/{page}"], "paged": True, "start": 5, "end": 1}
        resp = client.post("/api/sources", json=bad, headers=auth_header(operator_token))
        assert resp.status_code == 400

        ok = dict(base)
        ok["config"] = {
            "url": ["https://a.com/{page}"],
            "paged": True,
            "placeholder": "{page}",
            "start": 1,
            "end": 5,
        }
        assert client.post("/api/sources", json=ok, headers=auth_header(operator_token)).status_code == 201

    def test_max_gists_range(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "gist", "name": "g9", "config": {"max_gists": 999999}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400

    def test_script_requires_plugin(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "script", "name": "s1", "config": {}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400


class TestSourceTestConnection:
    def test_connection_probe_ok(self, client, operator_token, monkeypatch):
        from services import sources_service

        monkeypatch.setattr(sources_service, "probe_url", lambda *a, **k: {"ok": True, "status": 200, "cost_ms": 120})
        sid = client.post(
            "/api/sources",
            json={"type": "page", "name": "probe", "config": {"url": ["https://a.example.com"]}},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        resp = client.post(f"/api/sources/{sid}/test", headers=auth_header(operator_token))
        assert resp.json()["data"]["ok"] is True
        assert resp.json()["data"]["status"] == 200

    def test_connection_probe_fail(self, client, operator_token, monkeypatch):
        from services import sources_service

        monkeypatch.setattr(sources_service, "probe_url", lambda *a, **k: {"ok": False, "status": 403, "cost_ms": 80})
        sid = client.post(
            "/api/sources",
            json={"type": "page", "name": "probe2", "config": {"url": ["https://b.example.com"]}},
            headers=auth_header(operator_token),
        ).json()["data"]["id"]
        resp = client.post(f"/api/sources/{sid}/test", headers=auth_header(operator_token))
        assert resp.json()["data"]["ok"] is False


class TestSourceImportExport:
    def test_export_import_roundtrip(self, client, operator_token):
        client.post(
            "/api/sources",
            json={"type": "telegram", "name": "chan1", "config": {"pages": 3}},
            headers=auth_header(operator_token),
        )
        exported = client.get("/api/sources/export", headers=auth_header(operator_token)).json()["data"]
        assert exported["telegram"][0]["name"] == "chan1"

        # 同名合并而非覆盖：再导入同内容应幂等
        resp = client.post("/api/sources/import", json=exported, headers=auth_header(operator_token))
        assert resp.json()["data"]["created"] == 0 and resp.json()["data"]["merged"] == 1
        listing = client.get("/api/sources", headers=auth_header(operator_token))
        assert listing.json()["data"]["total"] == 1

    def test_import_drops_push_to_and_names_google(self, client, operator_token):
        payload = {
            "google": {"enable": True, "limit": 50, "push_to": ["free"]},
            "telegram": {"channels": {"ch1": {"pages": 2, "push_to": ["free"]}}},
        }
        client.post("/api/sources/import", json=payload, headers=auth_header(operator_token))
        sources = client.get("/api/sources", headers=auth_header(operator_token)).json()["data"]["items"]
        names = {s["name"] for s in sources}
        assert names == {"google", "ch1"}
        google = next(s for s in sources if s["name"] == "google")
        assert "push_to" not in google["config"]


class TestSourceSchema:
    def test_schema_endpoint_covers_all_types_with_examples(self, client, operator_token):
        data = client.get("/api/sources/schema", headers=auth_header(operator_token)).json()["data"]
        schemas = data["schemas"]
        assert set(schemas) == {"telegram", "github", "gist", "google", "yandex", "page", "repo", "script"}
        # telegram 标识字段为频道名；其余为源名称
        assert schemas["telegram"]["identity_label"] == "频道名"
        assert schemas["github"]["identity_label"] == "源名称"
        # 每个字段都有示例与说明
        for meta in schemas.values():
            for field in meta["fields"]:
                assert "example" in field and "label" in field and "hint" in field
        # script 插件枚举来自注册表
        plugins = next(f for f in schemas["script"]["fields"] if f["key"] == "plugin")["options"]
        assert "v2rayse" in plugins and "fofa" in plugins

    def test_github_requires_token_or_cookie(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "github", "name": "gh1", "config": {"pages": 2}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400
        assert "Token" in resp.json()["message"]

    def test_github_with_token_ok(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "github", "name": "gh2", "config": {"token": "ghp_fake", "pages": 2}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201

    def test_gist_requires_token(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "gist", "name": "g1", "config": {"mode": "timeline", "max_gists": 50}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400
        assert "Token" in resp.json()["message"]

    def test_gist_search_requires_cookie(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "gist", "name": "g2", "config": {"mode": "search", "token": "ghp_fake"}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 400
        assert "Cookie" in resp.json()["message"]

    def test_gist_search_full_config_ok(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={
                "type": "gist",
                "name": "g3",
                "config": {
                    "mode": "search", "gh_cookie": "user_session=abc", "token": "ghp_fake",
                    "patterns": ["/link/ ?sub=1"], "pages": 2, "max_gists": 100, "max_filesize": 65536,
                },
            },
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["config"]["mode"] == "search"

    def test_telegram_identity_is_channel_name(self, client, operator_token):
        resp = client.post(
            "/api/sources",
            json={"type": "telegram", "name": "oneclickvpnkeys", "config": {"pages": 5, "rename": "🚀"}},
            headers=auth_header(operator_token),
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["config"]["rename"] == "🚀"

    def test_import_legacy_config_normalized(self, client, operator_token):
        """旧 my-config crawl 节导入：字段归一化、push_to 丢弃。"""
        payload = {
            "telegram": {"channels": {"oneclickvpnkeys": {"pages": 5, "task": {"rename": "🚀"}, "push_to": ["free"]}}},
            "github": {"pages": 2, "exclude_repos": [], "patterns": [], "push_to": ["free"]},
            "gist": {"enable": True, "max_gists": 100, "patterns": [], "push_to": ["free"]},
        }
        resp = client.post("/api/sources/import", json=payload, headers=auth_header(operator_token))
        assert resp.status_code == 200
        # github/gist 缺凭证 → 跳过（导入 conservative）
        assert resp.json()["data"]["created"] == 1
        items = client.get("/api/sources", headers=auth_header(operator_token)).json()["data"]["items"]
        names = {i["name"] for i in items}
        assert "oneclickvpnkeys" in names
