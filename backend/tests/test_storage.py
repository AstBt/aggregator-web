# -*- coding: utf-8 -*-
"""存储目标管理 API 测试（FR-5.10~5.17, A14；v2.4 收归 admin）。"""

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
    return client.post(
        "/api/auth/login", json={"username": "operator1", "password": "pass1234"}
    ).json()["data"]["accessToken"]


class TestTargetCrud:
    def test_admin_crud(self, client, admin_token, tmp_path):
        resp = client.post(
            "/api/storage-targets",
            json={"type": "gist", "name": "gist-main", "config": {"gist_id": "6b08d288"}, "token": "ghp_fake"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201, resp.text
        tid = resp.json()["data"]["id"]
        assert "token" not in resp.json()["data"]  # 凭证不回显（FR-5.16）

        listing = client.get("/api/storage-targets", headers=auth_header(admin_token)).json()["data"]
        assert listing["total"] >= 2

        updated = client.put(
            f"/api/storage-targets/{tid}",
            json={"config": {"gist_id": "newid"}},
            headers=auth_header(admin_token),
        )
        assert updated.json()["data"]["config"]["gist_id"] == "newid"

        assert client.delete(f"/api/storage-targets/{tid}", headers=auth_header(admin_token)).status_code == 200

    def test_all_targets_equal(self, client, admin_token, db_session):
        """本地目标与远端目标一样可停可删（v2.3）。"""
        from models import StorageTarget

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        resp = client.post(f"/api/storage-targets/{target.id}/toggle", headers=auth_header(admin_token))
        assert resp.json()["data"]["enable"] is False
        resp = client.delete(f"/api/storage-targets/{target.id}", headers=auth_header(admin_token))
        assert resp.status_code == 200

    def test_operator_readonly(self, client, admin_token, operator_token):
        """v2.4：operator 对存储目标只读。"""
        assert client.get("/api/storage-targets", headers=auth_header(operator_token)).status_code == 200
        create = client.post(
            "/api/storage-targets",
            json={"type": "local", "name": "local2", "config": {"dir": "x"}},
            headers=auth_header(operator_token),
        )
        assert create.status_code == 403
        target = client.get("/api/storage-targets", headers=auth_header(operator_token)).json()["data"]["items"][0]
        toggle = client.post(f"/api/storage-targets/{target['id']}/toggle", headers=auth_header(operator_token))
        assert toggle.status_code == 403
        delete = client.delete(f"/api/storage-targets/{target['id']}", headers=auth_header(operator_token))
        assert delete.status_code == 403

    def test_duplicate_name_409(self, client, admin_token):
        client.post(
            "/api/storage-targets",
            json={"type": "local", "name": "dup-local", "config": {"dir": "d1"}},
            headers=auth_header(admin_token),
        )
        resp = client.post(
            "/api/storage-targets",
            json={"type": "local", "name": "dup-local", "config": {"dir": "d2"}},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 409

    def test_unknown_type_400(self, client, admin_token):
        resp = client.post(
            "/api/storage-targets",
            json={"type": "dropbox", "name": "x", "config": {}},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_token_masked_on_read(self, client, admin_token):
        client.post(
            "/api/storage-targets",
            json={"type": "gist", "name": "gm", "config": {"gist_id": "abc"}, "token": "ghp_supersecret"},
            headers=auth_header(admin_token),
        )
        listing = client.get("/api/storage-targets", headers=auth_header(admin_token)).json()["data"]["items"]
        target = next(t for t in listing if t["name"] == "gm")
        assert "ghp_supersecret" not in str(target)
        assert target["token_masked"].startswith("ghp_")


class TestTargetTestConnection:
    def test_local_dir_writable(self, client, admin_token, tmp_path):
        directory = tmp_path / "writable"
        directory.mkdir()
        resp = client.post(
            "/api/storage-targets",
            json={"type": "local", "name": "wt", "config": {"dir": str(directory)}},
            headers=auth_header(admin_token),
        )
        tid = resp.json()["data"]["id"]
        result = client.post(f"/api/storage-targets/{tid}/test", headers=auth_header(admin_token)).json()["data"]
        assert result["ok"] is True

    def test_local_dir_not_writable(self, client, admin_token):
        resp = client.post(
            "/api/storage-targets",
            json={"type": "local", "name": "nw", "config": {"dir": "Z:/nonexistent-dir-xyz"}},
            headers=auth_header(admin_token),
        )
        tid = resp.json()["data"]["id"]
        result = client.post(f"/api/storage-targets/{tid}/test", headers=auth_header(admin_token)).json()["data"]
        assert result["ok"] is False

    def test_remote_probe_mocked(self, client, admin_token, monkeypatch):
        from services import sources_service

        monkeypatch.setattr(
            sources_service, "probe_url", lambda *a, **k: {"ok": True, "status": 200, "cost_ms": 66}
        )
        resp = client.post(
            "/api/storage-targets",
            json={"type": "gist", "name": "gm2", "config": {"gist_id": "abc"}, "token": "ghp_x"},
            headers=auth_header(admin_token),
        )
        tid = resp.json()["data"]["id"]
        result = client.post(f"/api/storage-targets/{tid}/test", headers=auth_header(admin_token)).json()["data"]
        assert result["ok"] is True


class TestScheduleLifecycle:
    def test_target_deleted_disables_schedule(self, client, admin_token, db_session):
        """NFR-12：schedule 绑定目标被删 → 自动停用并标记原因。"""
        from models import Schedule, StorageTarget

        target = db_session.query(StorageTarget).filter_by(name="data-local").first()
        db_session.add(
            Schedule(name="s1", cron="0 9 * * *", mode="full", params={"bind_target_ids": [target.id]}, enable=True)
        )
        db_session.commit()
        client.delete(f"/api/storage-targets/{target.id}", headers=auth_header(admin_token))
        schedule = db_session.query(Schedule).filter_by(name="s1").first()
        assert schedule.enable is False
        assert schedule.disabled_reason
