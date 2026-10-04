# -*- coding: utf-8 -*-
"""pytest 共享夹具：独立临时库 + TestClient + 种子管理员。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("AGG_DATA_DIR", str(BACKEND_DIR / ".testdata"))
os.environ.setdefault("AGG_JWT_SECRET", "test-secret-key-for-pytest-only")
os.environ.setdefault("AGG_ADMIN_USER", "admin")
os.environ.setdefault("AGG_ADMIN_PASSWORD", "admin123")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """每个测试用例独立数据库文件。"""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AGG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AGG_DATABASE_URL", f"sqlite:///{data_dir / 'test.db'}")

    import config

    db_url = "sqlite:///" + (data_dir / "test.db").as_posix()
    config.settings.data_dir = data_dir
    config.settings.database_url = db_url
    config.settings.jwt_secret = "test-secret-key-for-pytest-only"
    config.settings.jwt_ttl_seconds = 3600

    import db

    db.engine.dispose()
    db.engine = db.create_engine_from_url(db_url)
    db.SessionLocal.configure(bind=db.engine)

    from models import Base

    Base.metadata.create_all(db.engine)

    from ratelimit import login_limiter

    login_limiter.reset()

    from main import create_app

    application = create_app()
    yield application
    db.engine.dispose()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session(app):
    from db import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def admin_token(client) -> str:
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["accessToken"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def operator_token(client, admin_token) -> str:
    """共享的 operator 账号令牌（原各测试文件重复定义，收敛至 conftest）。"""
    client.post(
        "/api/users",
        json={"username": "operator1", "password": "pass1234", "role": "operator"},
        headers=auth_header(admin_token),
    )
    return client.post(
        "/api/auth/login", json={"username": "operator1", "password": "pass1234"}
    ).json()["data"]["accessToken"]


@pytest.fixture()
def fake_engine():
    """注入确定性测试引擎（HermeticEngine）：无网络、产出可预期。"""
    from engine_adapter import runner as runner_module

    engine = runner_module.HermeticEngine(
        subscriptions=[("https://sub.example.com/a", "PAGE", True)],
        proxies=[
            {"name": "🚀 测试01", "type": "vless", "server": "hk01.example.com", "port": 443, "delay": 120},
            {"name": "🚀 测试02", "type": "vmess", "server": "sg02.example.net", "port": 80, "delay": 460},
            {"name": "🚀 测试03", "type": "hysteria2", "server": "hk04.example.com", "port": 36712, "delay": 190},
        ],
    )
    previous = runner_module.TaskRunner.instance().engine
    runner_module.TaskRunner.instance().engine = engine
    yield engine
    runner_module.TaskRunner.instance().engine = previous
