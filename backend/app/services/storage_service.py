# -*- coding: utf-8 -*-
"""存储目标服务：类型元数据、连通性探测、凭证加解密。"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from services import secrets

TYPES = {
    "local": {"name": "本地目录", "fields": ["dir", "keep"], "token": False, "probe": "dir"},
    "gist": {"name": "GitHub Gist", "fields": ["gist_id"], "token": True, "probe": "api"},
    "pastegg": {"name": "PasteGG", "fields": ["base"], "token": True, "probe": "api"},
    "pastefy": {"name": "Pastefy", "fields": ["base"], "token": True, "probe": "api"},
    "imperial": {"name": "Imperial", "fields": ["base"], "token": True, "probe": "api"},
    "qbin": {"name": "QBin", "fields": ["base"], "token": True, "probe": "api"},
}

_API_BASES = {
    "gist": "https://api.github.com/zen",
    "pastegg": "https://api.paste.gg",
    "pastefy": "https://pastefy.app",
    "imperial": "https://imperialb.in",
    "qbin": "https://qbin.me",
}


def validate_target(target_type: str, config: dict[str, Any], token: str) -> list[str]:
    errors: list[str] = []
    meta = TYPES.get(target_type)
    if meta is None:
        return [f"不支持的存储类型: {target_type}"]
    required = [f for f in meta["fields"] if f != "keep"]  # keep（快照保留份数）可选
    for field in required:
        if not str(config.get(field, "")).strip():
            errors.append(f"{meta['name']} 目标必须配置 {field}")
    if meta["token"] and not token:
        errors.append(f"{meta['name']} 目标必须提供访问令牌")
    return errors


def probe(target_type: str, config: dict[str, Any], token: str) -> dict:
    """测试连接：local 测目录可写；远端测 base/token 有效性（FR-5.12）。"""
    from services import sources_service

    if target_type == "local":
        directory = str(config.get("dir") or "")
        if not directory:
            return {"ok": False, "error": "未配置目录"}
        try:
            os.makedirs(directory, exist_ok=True)
            probe_file = os.path.join(directory, ".agg-probe")
            with open(probe_file, "w", encoding="utf8") as f:
                f.write("ok")
            os.remove(probe_file)
            return {"ok": True, "detail": "目录可写"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
    if target_type in TYPES:
        base = str(config.get("base") or _API_BASES.get(target_type, ""))
        result = sources_service.probe_url(base or _API_BASES[target_type])
        detail = "服务可达" if result["ok"] else "服务不可达"
        return {**result, "detail": detail + (" · 令牌已配置" if token else " · 未配置令牌")}
    return {"ok": False, "error": "未知类型"}


def encrypt_token(token: str) -> str:
    return secrets.encrypt(token)


def decrypt_token(token_ref: str) -> str:
    return secrets.decrypt(token_ref)


def masked(token_ref: str) -> str:
    plain = secrets.decrypt(token_ref) if token_ref else ""
    return secrets.mask(plain) if plain else ""


def temp_dir() -> str:
    return tempfile.gettempdir()
