# -*- coding: utf-8 -*-
"""爬取源服务：校验、连通性探测、配置导出/导入、引擎配置合成。"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import Any

SOURCE_TYPES = ("telegram", "github", "gist", "google", "yandex", "page", "repo", "script")

# 每种类型的数值字段范围（对应 config/models.py 约束）
_NUMERIC_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "telegram": {"pages": (1, 100)},
    "github": {"pages": (1, 50)},
    "gist": {"max_gists": (1, 5000), "max_filesize": (1024, 1 << 20), "pages": (1, 10)},
    "google": {"limit": (1, 1000), "days": (1, 3650)},
    "yandex": {"days": (0, 3650), "pages": (1, 50)},
    "page": {"start": (0, 100000), "end": (0, 100000)},
    "repo": {"commits": (1, 100)},
}
_REGEX_FIELDS = ("include", "exclude", "exclude_owners", "exclude_repos", "exclude_sites")


def validate_source_config(source_type: str, config: dict[str, Any]) -> list[str]:
    """返回字段级错误列表；空列表 = 通过（FR-3.5）。"""
    errors: list[str] = []
    if source_type not in SOURCE_TYPES:
        return [f"不支持的源类型: {source_type}"]

    for field, (lo, hi) in _NUMERIC_RANGES.get(source_type, {}).items():
        if field in config and config[field] is not None:
            value = config[field]
            if not isinstance(value, int) or isinstance(value, bool) or not (lo <= value <= hi):
                errors.append(f"{field} 须为 [{lo}, {hi}] 范围内的整数")

    for field in _REGEX_FIELDS:
        if field not in config:
            continue
        patterns = config[field] if isinstance(config[field], list) else [config[field]]
        for pattern in patterns:
            if not isinstance(pattern, str):
                errors.append(f"{field} 须为字符串或字符串数组")
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append(f"{field} 不是合法正则: {exc}")

    if source_type in ("telegram", "repo", "script") and not str(config.get("plugin", "")).strip():
        if source_type == "script":
            errors.append("script 源必须指定 plugin（插件名）")
    if source_type == "repo":
        if not str(config.get("username", "")).strip() or not str(config.get("repo", "")).strip():
            errors.append("repo 源必须指定 username 与 repo")
    if source_type == "page":
        urls = config.get("url") or []
        if isinstance(urls, str):
            urls = [urls]
        urls = [u for u in urls if str(u).strip()]
        if not urls:
            errors.append("page 源至少需要一个 URL")
        if config.get("paged"):
            placeholder = str(config.get("placeholder", "")).strip()
            if not placeholder or not any(placeholder in u for u in urls):
                errors.append("分页模式要求 placeholder 出现在 URL 中")
            if int(config.get("start", 1) or 1) > int(config.get("end", 1) or 1):
                errors.append("分页范围 start 不能大于 end")
    return errors


def probe_url(url: str, proxy: str = "", timeout: int = 15) -> dict:
    """对固定外部请求做一次探测（测试连接子组件）。"""
    handlers: list = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Aggregator-Web"})
    start = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as resp:
            return {"ok": 200 <= resp.status < 400, "status": resp.status, "cost_ms": int((time.monotonic() - start) * 1000)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "cost_ms": int((time.monotonic() - start) * 1000)}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "status": 0, "cost_ms": int((time.monotonic() - start) * 1000), "error": str(exc)}


def source_first_url(config: dict[str, Any]) -> str:
    """取源配置中第一个 URL（page 类测试连接用）。"""
    urls = config.get("url") or []
    if isinstance(urls, str):
        return urls.strip()
    for url in urls:
        if str(url).strip():
            return str(url).strip()
    return ""


# ---------- 导入/导出（与 my-config.json 的 crawl 节互转） ----------
def to_export_payload(sources: list) -> dict[str, list[dict]]:
    """DB → 按类型分组的导出结构（不含 push_to 等分组残留）。"""
    grouped: dict[str, list[dict]] = {}
    for source in sources:
        grouped.setdefault(source.type, []).append({"name": source.name, "config": source.config})
    return grouped


def from_import_payload(payload: dict) -> list[dict]:
    """导入源定义，兼容两种格式（FR-3.7）：

    1. 导出/DB 格式：{type: [{"name": ..., "config": ...}, ...]}
    2. my-config.json 的 crawl 节：telegram={channels:{...}}、github={...}、pages/scripts=[...]
    push_to 静默丢弃；无 name 的 section 以类型命名。
    """
    flat: dict[str, dict] = {}

    def _add(source_type: str, name: str, config: Any) -> None:
        flat[name] = {"type": source_type, "name": name, "config": _clean(config)}

    # 格式 1：按类型分组列表
    for key in SOURCE_TYPES:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("name"):
                    _add(key, str(item["name"]), item.get("config") or {})

    # 格式 2：my-config.json crawl 节
    telegram = payload.get("telegram")
    if isinstance(telegram, dict):
        rest = dict(telegram)
        channels = rest.pop("channels", {}) or {}
        for name, cfg in channels.items():
            _add("telegram", name, cfg)
        if rest.get("pages") or rest.get("enable") is not None:
            _add("telegram", "telegram", rest)
    for key in ("github", "gist", "google", "yandex"):
        if isinstance(payload.get(key), dict):
            _add(key, key, payload[key])
    for item in payload.get("pages") or []:
        name = item.get("name") or source_first_url(item.get("config") or item) or f"page-{len(flat)}"
        _add("page", name, item.get("config") or item)
    for item in payload.get("repositories") or []:
        name = f"{item.get('username', '')}/{item.get('repo', '')}".strip("/") or f"repo-{len(flat)}"
        _add("repo", name, item)
    for item in payload.get("scripts") or []:
        name = item.get("plugin") or f"script-{len(flat)}"
        _add("script", name, item)
    return list(flat.values())


def _clean(config: Any) -> dict:
    if not isinstance(config, dict):
        return {}
    cleaned = dict(config)
    cleaned.pop("push_to", None)
    task = cleaned.get("task")
    if isinstance(task, dict):
        task = dict(task)
        task.pop("push_to", None)
        cleaned["task"] = task
    return cleaned
