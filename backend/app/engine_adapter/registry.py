# -*- coding: utf-8 -*-
"""引擎适配：插件注册表查询（复用 subscribe/crawl/channels/plugins）。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

SUBSCRIBE_DIR = Path(__file__).resolve().parents[3] / "subscribe"
_LOCK = threading.Lock()
_CACHE: frozenset[str] | None = None


def _ensure_engine_on_path() -> None:
    path = str(SUBSCRIBE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


def _load_plugins() -> frozenset[str]:
    _ensure_engine_on_path()
    try:
        from crawl.channels.plugins import PLUGINS  # type: ignore

        return frozenset(PLUGINS)
    except Exception:
        return frozenset()


def _plugin_names() -> frozenset[str]:
    """已注册插件集合；导入失败不缓存（下次可重试）。"""
    global _CACHE
    with _LOCK:
        if _CACHE:
            return _CACHE
        names = _load_plugins()
        if names:
            _CACHE = names
        return names


def plugin_names() -> list[str]:
    """已注册插件列表（稳定顺序）。"""
    return sorted(_plugin_names())


def plugin_exists(name: str) -> bool:
    if not name:
        return False
    return name in _plugin_names()
