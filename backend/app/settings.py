# -*- coding: utf-8 -*-
"""运行配置：环境变量优先，其次默认值。"""

from __future__ import annotations

import os
import secrets as _secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
SUBSCRIBE_DIR = PROJECT_DIR / "subscribe"


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("AGG_DATA_DIR", str(PROJECT_DIR / "data")))
        self.database_url = os.environ.get(
            "AGG_DATABASE_URL", "sqlite:///" + (self.data_dir / "aggregator.db").as_posix()
        )
        self.jwt_secret = self._resolve_jwt_secret()
        self.jwt_ttl_seconds = int(os.environ.get("AGG_JWT_TTL", str(12 * 3600)))
        self.admin_username = os.environ.get("AGG_ADMIN_USER", "admin")
        self.admin_password = os.environ.get("AGG_ADMIN_PASSWORD", "admin123")
        self.host = os.environ.get("AGG_HOST", "127.0.0.1")
        self.port = int(os.environ.get("AGG_PORT", "8080"))
        self.frontend_dist = Path(os.environ.get("AGG_FRONTEND_DIST", str(PROJECT_DIR / "frontend" / "dist")))
        # 登录失败锁定：5 次 / 15 分钟；限流 10 次/分钟·IP
        self.login_max_fails = 5
        self.login_lock_minutes = 15
        self.ratelimit_per_minute = 10

    def _resolve_jwt_secret(self) -> str:
        """环境变量优先；否则读取/生成数据目录下的密钥文件（首次启动自动生成）。"""
        secret = os.environ.get("AGG_JWT_SECRET", "").strip()
        if secret:
            return secret
        key_file = self.data_dir / ".secret.jwt"
        try:
            if key_file.is_file():
                stored = key_file.read_text(encoding="utf8").strip()
                if stored:
                    return stored
            generated = _secrets.token_urlsafe(48)
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(generated, encoding="utf8")
            return generated
        except OSError:
            # 数据目录不可写时退回进程内随机密钥（重启后会话失效，不阻断启动）
            return _secrets.token_urlsafe(48)


settings = Settings()
