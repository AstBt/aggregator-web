# -*- coding: utf-8 -*-
"""爬取源服务：校验（Schema 驱动）、连通性探测、配置导入/导出。"""

from __future__ import annotations

from typing import Any

from services import source_schema


def validate_source_config(source_type: str, config: dict[str, Any]) -> list[str]:
    """字段级校验：委托 source_schema（单一事实源）。"""
    return source_schema.validate_source_config(source_type, config)


def probe_url(url: str, proxy: str = "", timeout: int = 15) -> dict:
    """对固定外部请求做一次探测（测试连接子组件）。"""
    import time
    import urllib.error
    import urllib.request

    handlers: list = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Aggregator-Web"})
    start = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as resp:
            return {
                "ok": 200 <= resp.status < 400,
                "status": resp.status,
                "cost_ms": int((time.monotonic() - start) * 1000),
            }
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
    grouped: dict[str, list[dict]] = {}
    for source in sources:
        grouped.setdefault(source.type, []).append({"name": source.name, "config": source.config})
    return grouped


def from_import_payload(payload: dict) -> list[dict]:
    """导入源定义，兼容两种格式：

    1. 导出/DB 格式：{type: [{"name": ..., "config": ...}, ...]}
    2. my-config.json 的 crawl 节：telegram={channels:{...}}、github={...}、pages/scripts=[...]

    push_to 等分组残留字段静默丢弃；无 name 的 section 以类型命名。
    """
    flat: dict[str, dict] = {}

    def _add(source_type: str, name: str, config: Any) -> None:
        flat[name] = {"type": source_type, "name": name, "config": _clean(source_type, config)}

    # 格式 1：按类型分组列表
    for key in source_schema.SOURCE_SCHEMA:
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
        # 节级 pages/exclude 对该节下所有频道生效（旧配置语义）
        section_pages = rest.get("pages")
        for name, cfg in channels.items():
            channel_cfg = _telegram_from_legacy(cfg)
            if section_pages and "pages" not in channel_cfg:
                channel_cfg["pages"] = section_pages
            _add("telegram", name, channel_cfg)

    for key in ("github", "gist", "google", "yandex"):
        if isinstance(payload.get(key), dict):
            _add(key, key, _legacy_common(payload[key]))
    for item in payload.get("pages") or []:
        name = item.get("name") or source_first_url(item.get("config") or item) or f"page-{len(flat)}"
        _add("page", name, _legacy_common(item.get("config") or item))
    for item in payload.get("repositories") or []:
        name = f"{item.get('username', '')}/{item.get('repo', '')}".strip("/") or f"repo-{len(flat)}"
        _add("repo", name, _legacy_common(item))
    for item in payload.get("scripts") or []:
        name = item.get("plugin") or f"script-{len(flat)}"
        _add("script", name, _legacy_common(item))
    return list(flat.values())


def _clean(source_type: str, config: Any) -> dict:
    """按 Schema 过滤字段：丢弃不支持的键，保留受支持的键（含扩展凭证字段）。"""
    if not isinstance(config, dict):
        return {}
    allowed = {f["key"] for f in source_schema.SOURCE_SCHEMA.get(source_type, {}).get("fields", [])}
    return {k: v for k, v in config.items() if k in allowed}


def _telegram_from_legacy(cfg: dict) -> dict:
    """旧配置频道节 → 新字段（task.rename 平铺为 rename）。"""
    cfg = _legacy_common(cfg)
    task = cfg.pop("task", None)
    if isinstance(task, dict) and task.get("rename"):
        cfg["rename"] = task["rename"]
    return cfg


def _legacy_common(config: Any) -> dict:
    if not isinstance(config, dict):
        return {}
    cleaned = dict(config)
    cleaned.pop("push_to", None)
    task = cleaned.pop("task", None)
    if isinstance(task, dict):
        for key in ("include", "exclude", "rename"):
            if task.get(key) and not cleaned.get(key):
                cleaned[key] = task[key]
    return cleaned
