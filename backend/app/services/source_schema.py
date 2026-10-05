# -*- coding: utf-8 -*-
"""爬取源配置 Schema：每种源类型支持的字段、示例与校验规则的单一事实源。

字段类型与渠道实现（subscribe/crawl/channels/*.py 与 config/models.py）严格对齐：
不支持的字段不存在，支持的字段给出默认示例；前端据此动态渲染表单（GET /api/sources/schema）。
"""

from __future__ import annotations

import re
from typing import Any

# 字段类型：str / int / bool / regex / list / kv / enum / password
# 通用键：key, label, type, required, default, example, hint, options, depends
SOURCE_SCHEMA: dict[str, dict[str, Any]] = {
    "telegram": {
        "label": "Telegram 频道",
        "icon": "📨",
        "identity": "channel",  # 标识字段即 name（频道名）
        "identity_label": "频道名",
        "fields": [
            {"key": "pages", "label": "翻页数", "type": "int", "default": 5, "example": "5",
             "hint": "每个频道向前翻页抓取的页数（1-100）"},
            {"key": "include", "label": "包含正则", "type": "regex", "default": "", "example": "(v2ray|clash)",
             "hint": "只保留匹配的订阅链接，留空不限制"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(过期|失效)",
             "hint": "命中即丢弃，留空不限制"},
            {"key": "rename", "label": "节点重命名", "type": "str", "default": "", "example": "🚀",
             "hint": "该频道节点统一加的前缀，留空不改名"},
        ],
    },
    "github": {
        "label": "GitHub 搜索",
        "icon": "🐙",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "token", "label": "GitHub Token", "type": "password", "required": False, "default": "",
             "example": "ghp_xxxxxxxxxxxxxxxxxxxx", "hint": "任意 scope 的 classic PAT；与 Cookie 二选一，均填写时优先 Token（REST API）"},
            {"key": "cookie", "label": "GitHub Cookie", "type": "password", "required": False, "default": "",
             "example": "user_session=1MPr7Ts5…", "hint": "浏览器登录态（user_session 值），无 Token 时走网页版搜索"},
            {"key": "pages", "label": "搜索页数", "type": "int", "default": 2, "example": "2",
             "hint": "每个关键词翻页数（1-50）"},
            {"key": "patterns", "label": "搜索关键词", "type": "list", "default": [], "example": "/api/v1/client/subscribe?token=",
             "hint": "空格分隔多个词组（AND 关系）；留空使用内置模式"},
            {"key": "exclude_repos", "label": "排除仓库", "type": "list", "default": [], "example": "wzdnzd/aggregator",
             "hint": "支持正则，命中的仓库不抓取"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(test|demo)",
             "hint": "对抓取结果生效"},
        ],
    },
    "gist": {
        "label": "Gist",
        "icon": "📄",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "mode", "label": "抓取模式", "type": "enum", "default": "timeline", "options": ["timeline", "search"],
             "example": "timeline", "hint": "timeline=扫描公开 gist 时间线；search=按关键词搜索（需 Cookie）"},
            {"key": "gh_cookie", "label": "GitHub Cookie", "type": "password", "default": "",
             "example": "user_session=1MPr7Ts5…", "hint": "搜索模式必填：浏览器登录态（user_session 值）",
             "depends": {"mode": "search"}, "required_when": {"mode": "search"}},
            {"key": "token", "label": "GitHub Token", "type": "password", "default": "",
             "example": "ghp_xxxxxxxxxxxxxxxxxxxx", "hint": "搜索模式必填：任意 scope PAT（配合 Cookie 读取 gist 内容）",
             "depends": {"mode": "search"}, "required_when": {"mode": "search"}},
            {"key": "patterns", "label": "搜索关键词", "type": "list", "default": [], "example": "/link/ ?sub=1",
             "hint": "仅搜索模式；空格分隔多个词组（AND 关系）", "depends": {"mode": "search"}},
            {"key": "pages", "label": "搜索页数", "type": "int", "default": 2, "example": "2",
             "hint": "仅搜索模式（1-10）", "depends": {"mode": "search"}},
            {"key": "max_gists", "label": "扫描数量上限", "type": "int", "default": 100, "example": "100",
             "hint": "最多检查多少个 gist（1-5000）"},
            {"key": "max_filesize", "label": "文件大小上限", "type": "int", "default": 65536, "example": "65536",
             "hint": "单文件字节数上限（≥1024），超过跳过"},
            {"key": "include", "label": "包含正则", "type": "regex", "default": "", "example": "(clash|v2ray)",
             "hint": "对 gist 内容提取的订阅生效", "depends": {"mode": "timeline"}},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(spam)",
             "hint": "对 gist 内容提取的订阅生效", "depends": {"mode": "timeline"}},
            {"key": "exclude_owners", "label": "排除作者", "type": "list", "default": [], "example": "someuser",
             "hint": "支持正则，命中的 gist 作者不抓取", "depends": {"mode": "timeline"}},
        ],
    },
    "google": {
        "label": "Google 搜索",
        "icon": "🔍",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "limit", "label": "结果上限", "type": "int", "default": 100, "example": "100",
             "hint": "每个关键词最多返回条数（1-1000）"},
            {"key": "days", "label": "时间范围", "type": "int", "default": 7, "example": "7",
             "hint": "最近 N 天的搜索结果"},
            {"key": "exclude_sites", "label": "排除站点", "type": "list", "default": [], "example": "github.com",
             "hint": "排除指定域名的搜索结果"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(login)",
             "hint": "对抓取结果生效"},
        ],
    },
    "yandex": {
        "label": "Yandex 搜索",
        "icon": "🔎",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "days", "label": "时间范围", "type": "int", "default": 3, "example": "3",
             "hint": "最近 N 天的搜索结果"},
            {"key": "pages", "label": "翻页数", "type": "int", "default": 5, "example": "5",
             "hint": "每个关键词翻页数（1-50）"},
            {"key": "exclude_sites", "label": "排除站点", "type": "list", "default": [], "example": "yandex.ru",
             "hint": "排除指定域名的搜索结果"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(captcha)",
             "hint": "对抓取结果生效"},
        ],
    },
    "page": {
        "label": "通用网页",
        "icon": "🌐",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "url", "label": "URL 列表", "type": "list", "required": True, "default": [], "example": "https://example.com/free/node",
             "hint": "每行一条，从页面中提取订阅链接"},
            {"key": "paged", "label": "分页抓取", "type": "bool", "default": False, "example": "false",
             "hint": "URL 中含占位符时按页码范围展开"},
            {"key": "placeholder", "label": "分页占位符", "type": "str", "default": "{page}", "example": "{page}",
             "hint": "URL 中被替换为页码的标记", "depends": {"paged": True}},
            {"key": "start", "label": "起始页", "type": "int", "default": 1, "example": "1",
             "hint": "分页起始页码", "depends": {"paged": True}},
            {"key": "end", "label": "结束页", "type": "int", "default": 5, "example": "5",
             "hint": "分页结束页码（≥起始页）", "depends": {"paged": True}},
            {"key": "headers", "label": "请求头", "type": "kv", "default": {}, "example": "Referer: https://example.com",
             "hint": "键值对，随请求发送（如 Referer / Cookie）"},
            {"key": "include", "label": "包含正则", "type": "regex", "default": "", "example": "(sub|link)",
             "hint": "只保留匹配的订阅链接"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(expired)",
             "hint": "命中即丢弃"},
        ],
    },
    "repo": {
        "label": "GitHub 仓库",
        "icon": "📦",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "username", "label": "仓库所有者", "type": "str", "required": True, "default": "", "example": "wzdnzd",
             "hint": "GitHub 用户名或组织名"},
            {"key": "repo", "label": "仓库名", "type": "str", "required": True, "default": "", "example": "aggregator",
             "hint": "被监控的仓库"},
            {"key": "commits", "label": "检查 commits 数", "type": "int", "default": 3, "example": "3",
             "hint": "每个仓库向前检查的提交数（1-100）"},
            {"key": "exclude", "label": "排除正则", "type": "regex", "default": "", "example": "(archive)",
             "hint": "对抓取结果生效"},
        ],
    },
    "script": {
        "label": "脚本插件",
        "icon": "🧪",
        "identity": "name",
        "identity_label": "源名称",
        "fields": [
            {"key": "plugin", "label": "插件", "type": "enum", "required": True, "default": "", "options": [],
             "example": "v2rayse", "hint": "插件列表由后端注册表提供（fofa / v2rayse / v2rayfree / tempairport / scaner / gitforks / dynamic）"},
            {"key": "persist", "label": "持久化文件", "type": "str", "default": "", "example": "v2rayse-state.json",
             "hint": "插件断点续爬状态文件名，留空不持久化"},
            {"key": "options", "label": "插件参数", "type": "kv", "default": {}, "example": "email: you@example.com",
             "hint": "键值对，按插件文档传入（如 fofa 的 email/key）"},
        ],
    },
}

_NUMERIC_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "telegram": {"pages": (1, 100)},
    "github": {"pages": (1, 50)},
    "gist": {"max_gists": (1, 5000), "max_filesize": (1024, 1 << 20), "pages": (1, 10)},
    "google": {"limit": (1, 1000), "days": (1, 3650)},
    "yandex": {"days": (0, 3650), "pages": (1, 50)},
    "page": {"start": (0, 100000), "end": (0, 100000)},
    "repo": {"commits": (1, 100)},
}


def schema_for(source_type: str) -> dict | None:
    return SOURCE_SCHEMA.get(source_type)


def all_schemas(plugin_options: list[str] | None = None) -> dict[str, dict]:
    """完整 schema（script 的插件枚举由注册表注入）。"""
    schemas = {key: dict(value) for key, value in SOURCE_SCHEMA.items()}
    script = schemas.get("script")
    if script and plugin_options:
        for field in script["fields"]:
            if field["key"] == "plugin":
                field["options"] = list(plugin_options)
    return schemas


def field_enabled(field: dict, config: dict) -> bool:
    depends = field.get("depends") or {}
    return all(config.get(k) == v for k, v in depends.items())


def field_required(field: dict, config: dict) -> bool:
    if field.get("required"):
        return True
    for key, value in (field.get("required_when") or {}).items():
        if config.get(key) == value:
            return True
    return False


def defaults_for(source_type: str) -> dict:
    meta = SOURCE_SCHEMA.get(source_type)
    if not meta:
        return {}
    return {f["key"]: f["default"] for f in meta["fields"]}


def validate_source_config(source_type: str, config: dict) -> list[str]:
    """Schema 驱动的字段级校验；空列表 = 通过。"""
    meta = SOURCE_SCHEMA.get(source_type)
    if meta is None:
        return [f"不支持的源类型: {source_type}"]
    if not isinstance(config, dict):
        return ["配置必须为对象"]

    errors: list[str] = []
    for field in meta["fields"]:
        key = field["key"]
        if not field_enabled(field, config):
            continue  # 条件字段未启用：跳过校验（值被忽略）
        value = config.get(key)
        if field_required(field, config) and (value is None or (isinstance(value, str) and not value.strip())):
            errors.append(f"{field['label']} 为必填项")
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        kind = field["type"]
        if kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{field['label']} 须为整数")
                continue
            bounds = _NUMERIC_RANGES.get(source_type, {}).get(key)
            if bounds and not (bounds[0] <= value <= bounds[1]):
                errors.append(f"{field['label']} 须在 [{bounds[0]}, {bounds[1]}] 范围内")
        elif kind in ("regex", "str", "password", "enum"):
            if not isinstance(value, str):
                errors.append(f"{field['label']} 须为字符串")
                continue
            if kind == "regex":
                try:
                    re.compile(value)
                except re.error as exc:
                    errors.append(f"{field['label']} 不是合法正则: {exc}")
            if kind == "enum" and field.get("options") and value not in field["options"]:
                errors.append(f"{field['label']} 须为: {' / '.join(field['options'])}")
        elif kind in ("list", "kv"):
            if not isinstance(value, (list, dict)):
                errors.append(f"{field['label']} 格式不正确")

    if source_type == "page":
        urls = [u for u in (config.get("url") or []) if str(u).strip()]
        if config.get("paged"):
            placeholder = str(config.get("placeholder", "")).strip()
            if placeholder and not any(placeholder in u for u in urls):
                errors.append("分页占位符必须出现在某个 URL 中")
            if int(config.get("start", 1) or 1) > int(config.get("end", 1) or 1):
                errors.append("分页起始页不能大于结束页")

    # 跨字段校验（凭证规则，与渠道实现的读取条件对齐）
    if source_type == "github":
        if not str(config.get("token", "")).strip() and not str(config.get("cookie", "")).strip():
            errors.append("GitHub 搜索需要 Token 或 Cookie 至少其一（均填写时优先 Token）")
    if source_type == "gist":
        if not str(config.get("token", "")).strip():
            errors.append("Gist 抓取需要 GitHub Token（读取 gist 内容）")
        if config.get("mode") == "search" and not str(config.get("gh_cookie", "")).strip():
            errors.append("Gist 搜索模式需要 GitHub Cookie（网页搜索登录态）")
    return errors
