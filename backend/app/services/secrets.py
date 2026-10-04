# -*- coding: utf-8 -*-
"""凭证加密存储：Fernet 对称加密，密钥文件位于数据目录（NFR-1 / FR-5.16）。"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

from config import settings

_KEY_FILE = settings.data_dir / ".secret.key"


def _load_or_create_key() -> bytes:
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.is_file():
        return _KEY_FILE.read_bytes()
    seed = (settings.jwt_secret or os.urandom(32).hex()).encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    _KEY_FILE.write_bytes(key)
    return key


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return Fernet(_load_or_create_key()).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return Fernet(_load_or_create_key()).decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def mask(token: str) -> str:
    """掩码展示：仅保留前 4 后 2。"""
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return token[:4] + "•" * (len(token) - 6) + token[-2:]
