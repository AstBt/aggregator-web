# -*- coding: utf-8 -*-
"""参数服务：爬取/验活参数读写、探测连通性。"""

from __future__ import annotations

from typing import Any

import db
from models import Setting

CRAWL_KEYS = ("exclude", "include", "exclude_task", "max_fails", "include_nodes")
ALIVE_KEYS = (
    "timeout",
    "max_delay",
    "num_threads",
    "retry",
    "test_urls",
    "primary_test_url",
    "keep_published_on_controller_error",
    "regularize",
)
PROXY_KEYS = ("enable", "address", "test_url")

_ALIVE_LIMITS = {"timeout": (500, 30000), "max_delay": (500, 15000), "num_threads": (1, 128), "retry": (1, 10)}


def get_group(key: str, session) -> dict[str, Any]:
    setting = session.get(Setting, key)
    return dict(setting.value) if setting else {}


def save_group(key: str, value: dict[str, Any], session) -> dict[str, Any]:
    setting = session.get(Setting, key) or Setting(key=key, value={})
    setting.value = value
    session.add(setting)
    session.commit()
    return setting.value


def get_crawl(session) -> dict[str, Any]:
    return get_group("crawl", session)


def put_crawl(session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_crawl(session)
    return save_group("crawl", _merge(current, payload, CRAWL_KEYS + ("proxy",)), session)


def get_alive(session) -> dict[str, Any]:
    return get_group("alive", session)


def put_alive(session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_alive(session)
    merged = _merge(current, payload, ALIVE_KEYS)
    for key, (lo, hi) in _ALIVE_LIMITS.items():
        if key in merged and not (lo <= int(merged[key]) <= hi):
            raise ValueError(f"{key} 须为 [{lo}, {hi}] 范围内的整数")
    if not merged.get("test_urls"):
        raise ValueError("至少保留一个测试 URL")
    primary = merged.get("primary_test_url") or merged["test_urls"][0]
    if primary not in merged["test_urls"]:
        raise ValueError("生效测试 URL 必须存在于列表中")
    merged["primary_test_url"] = primary
    return save_group("alive", merged, session)


def liveness_uses_proxy() -> bool:
    """实际节点验活始终经节点直连，不经过本地代理（FR-3.14a 语义固化）。"""
    return False


def _merge(current: dict[str, Any], payload: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    merged = dict(current)
    for key in allowed:
        if key in payload and payload[key] is not None:
            merged[key] = payload[key]
    return merged


def probe_url(url: str, proxy: str = "", timeout: int = 15) -> dict:
    """复用 sources_service 的探测实现（统一网络出口逻辑）。"""
    from services import sources_service

    return sources_service.probe_url(url, proxy=proxy, timeout=timeout)


def probe_via_proxy(session) -> dict:
    """经本地代理探测（爬取参数页「测试连接」）。"""
    from services import sources_service

    crawl = get_crawl(session)
    proxy = crawl.get("proxy") or {}
    if not proxy.get("enable") or not proxy.get("address"):
        return {"ok": False, "status": 0, "cost_ms": 0, "error": "本地代理未启用"}
    return sources_service.probe_url(proxy.get("test_url") or "https://api.github.com/zen", proxy=proxy["address"])
