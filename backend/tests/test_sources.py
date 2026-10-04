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
            json={"type": "gist", "name": "g1", "config": {"max_gists": 50}},
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
        assert "include" in resp.json()["message"]

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
