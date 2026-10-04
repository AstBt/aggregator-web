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
