# -*- coding: utf-8 -*-
"""初始化：建表、种子管理员、默认设置、默认本地存储目标。"""

from __future__ import annotations

import db
from models import Setting, StorageTarget, User
from security import hash_password

DEFAULT_SETTINGS: dict[str, dict] = {
    "crawl": {
        "exclude": "",
        "include": "",
        "exclude_task": "",
        "max_fails": 5,
        "include_nodes": True,
    },
    "proxy": {"enable": False, "address": "http://127.0.0.1:7897", "test_url": "https://api.github.com/zen"},
    "alive": {
        "timeout": 5000,
        "max_delay": 5000,
        "num_threads": 64,
        "retry": 3,
        "test_urls": ["https://www.google.com/generate_204"],
        "keep_published_on_controller_error": True,
        "regularize": True,
    },
    "export": {"node_limit": 5000, "emoji": True},
    "system": {"nodes_keep_runs": 20},
}


def init_db() -> None:
    from config import settings

    db.Base.metadata.create_all(db.engine)
    session = db.SessionLocal()
    try:
        if session.query(User).filter_by(username=settings.admin_username).first() is None:
            session.add(
                User(
                    username=settings.admin_username,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    enable=True,
                )
            )
        for key, value in DEFAULT_SETTINGS.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))
        if session.query(StorageTarget).filter_by(name="data-local").first() is None:
            session.add(
                StorageTarget(
                    type="local",
                    name="data-local",
                    enable=True,
                    config={"dir": str(settings.data_dir / "local"), "keep": 5},
                )
            )
        session.commit()
    finally:
        session.close()
