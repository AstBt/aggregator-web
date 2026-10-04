# -*- coding: utf-8 -*-
"""用户管理 API 测试（FR-1.9~1.11, A2, RBAC）。"""

from __future__ import annotations

from conftest import auth_header


def _login(client, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["accessToken"]


class TestUserCrud:
    def test_admin_creates_operator(self, client, admin_token):
        resp = client.post(
            "/api/users",
            json={"username": "zhangsan", "password": "pass1234", "role": "operator"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["role"] == "operator"

    def test_duplicate_username_409(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "dup", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        again = client.post(
            "/api/users",
            json={"username": "dup", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        assert again.status_code == 409

    def test_list_users_paginated(self, client, admin_token):
        for i in range(3):
            resp = client.post(
                "/api/users",
                json={"username": f"user{i}", "password": "pass1234", "role": "viewer"},
                headers=auth_header(admin_token),
            )
            assert resp.status_code == 201, resp.text
        resp = client.get("/api/users?page=1&page_size=2", headers=auth_header(admin_token))
        body = resp.json()["data"]
        assert body["total"] >= 4 and len(body["items"]) == 2

    def test_disable_user_invalidates_their_token(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "lisi", "password": "pass1234", "role": "operator"},
            headers=auth_header(admin_token),
        )
        token = _login(client, "lisi", "pass1234")
        assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

        users = client.get("/api/users", headers=auth_header(admin_token)).json()["data"]["items"]
        lisi = next(u for u in users if u["username"] == "lisi")
        resp = client.put(f"/api/users/{lisi['id']}", json={"enable": False}, headers=auth_header(admin_token))
        assert resp.status_code == 200
        # 禁用后令牌 60 秒内失效（token_version 机制）
        assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401

    def test_role_change_takes_effect(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "wangwu", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        token = _login(client, "wangwu", "pass1234")
        users = client.get("/api/users", headers=auth_header(admin_token)).json()["data"]["items"]
        uid = next(u["id"] for u in users if u["username"] == "wangwu")
        client.put(f"/api/users/{uid}", json={"role": "operator"}, headers=auth_header(admin_token))
        # 旧令牌因 token_version +1 失效，重新登录后为新角色
        assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
        new_token = _login(client, "wangwu", "pass1234")
        me = client.get("/api/auth/me", headers=auth_header(new_token)).json()["data"]
        assert me["role"] == "operator"

    def test_cannot_delete_last_admin(self, client, admin_token):
        me = client.get("/api/auth/me", headers=auth_header(admin_token)).json()["data"]
        resp = client.delete(f"/api/users/{me['id']}", headers=auth_header(admin_token))
        assert resp.status_code == 400
        assert "管理员" in resp.json()["message"]

    def test_cannot_disable_last_admin(self, client, admin_token):
        me = client.get("/api/auth/me", headers=auth_header(admin_token)).json()["data"]
        resp = client.put(f"/api/users/{me['id']}", json={"enable": False}, headers=auth_header(admin_token))
        assert resp.status_code == 400


class TestRbac:
    def test_operator_cannot_manage_users(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "op1", "password": "pass1234", "role": "operator"},
            headers=auth_header(admin_token),
        )
        op_token = _login(client, "op1", "pass1234")
        assert client.get("/api/users", headers=auth_header(op_token)).status_code == 403
        assert (
            client.post(
                "/api/users",
                json={"username": "x", "password": "pass1234", "role": "viewer"},
                headers=auth_header(op_token),
            ).status_code
            == 403
        )

    def test_viewer_cannot_manage_users(self, client, admin_token):
        client.post(
            "/api/users",
            json={"username": "vw1", "password": "pass1234", "role": "viewer"},
            headers=auth_header(admin_token),
        )
        vw_token = _login(client, "vw1", "pass1234")
        assert client.get("/api/users", headers=auth_header(vw_token)).status_code == 403

    def test_no_token_401(self, client):
        assert client.get("/api/users").status_code == 401
