# -*- coding: utf-8 -*-
"""引擎适配：插件注册表查询（复用 subscribe/crawl/channels/plugins）。"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

SUBSCRIBE_DIR = Path(__file__).resolve().parents[3] / "subscribe"


def _ensure_engine_on_path() -> None:
    path = str(SUBSCRIBE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


@lru_cache(maxsize=1)
def _plugin_names() -> frozenset[str]:
    _ensure_engine_on_path()
    try:
        from crawl.channels.plugins import __all__ as names  # type: ignore

        return frozenset(names)
    except Exception:
        return frozenset()


def plugin_exists(name: str) -> bool:
    if not name:
        return False
    return name in _plugin_names()
