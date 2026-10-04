# -*- coding: utf-8 -*-
"""认证 API 测试（FR-1.1~1.8, A1）。"""

from __future__ import annotations

from conftest import auth_header


class TestLogin:
    def test_success_returns_token_and_me(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["data"]["accessToken"]

        me = client.get("/api/auth/me", headers=auth_header(body["data"]["accessToken"]))
        assert me.status_code == 200
        assert me.json()["data"]["username"] == "admin"
        assert me.json()["data"]["role"] == "admin"

    def test_wrong_password_401_generic_message(self, client):
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "用户名或密码错误"

    def test_unknown_user_same_message(self, client):
        resp = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
        assert resp.status_code == 401
        assert resp.json()["message"] == "用户名或密码错误"

    def test_lock_after_five_failures(self, client):
        for _ in range(5):
            client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        ok = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert ok.status_code == 423
        assert "锁定" in ok.json()["message"]

    def test_ratelimit_per_ip_and_user(self, client):
        for _ in range(10):
            client.post("/api/auth/login", json={"username": "someone", "password": "x"})
        blocked = client.post("/api/auth/login", json={"username": "someone", "password": "x"})
        assert blocked.status_code == 429

    def test_me_without_token_401(self, client):
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    def test_logout_invalidates_token(self, client):
        token = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()[
            "data"
        ]["accessToken"]
        assert client.post("/api/auth/logout", headers=auth_header(token)).status_code == 200
        assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401


class TestPasswordChange:
    def test_change_password_invalidates_other_sessions(self, client):
        token = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()[
            "data"
        ]["accessToken"]
        resp = client.put(
            "/api/auth/password",
            json={"old_password": "admin123", "new_password": "newpass123"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        # 修改后旧令牌失效
        assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
        # 新密码可登录
        again = client.post("/api/auth/login", json={"username": "admin", "password": "newpass123"})
        assert again.status_code == 200

    def test_wrong_old_password_400(self, client, admin_token):
        resp = client.put(
            "/api/auth/password",
            json={"old_password": "wrong", "new_password": "newpass123"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 400

    def test_short_new_password_rejected(self, client, admin_token):
        resp = client.put(
            "/api/auth/password",
            json={"old_password": "admin123", "new_password": "short"},
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 422
