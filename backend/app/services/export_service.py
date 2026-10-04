# -*- coding: utf-8 -*-
"""导出服务：节点 → Clash / V2Ray(mixed) / SingBox（纯 Python 转换，等价 subconverter 输出）。

说明：Web 端导出不fork subconverter 二进制，而是在服务内完成等价的协议转换
（同一节点集合 → 同一客户端格式），保证无外部依赖、可完整单测（PRD FR-5.5）。
"""

from __future__ import annotations

import base64
import json
import urllib.parse

import yaml

from config import settings
from services import secrets  # noqa: F401  （保持服务层依赖集中）

TARGETS = ("clash", "v2ray", "singbox")


def node_limit(session) -> int:
    from models import Setting

    setting = session.get(Setting, "export")
    return int((setting.value if setting else {}).get("node_limit", 5000) or 5000)


def _link(node: dict) -> str:
    """单节点分享链接（v2ray 系列）。"""
    raw = node.get("raw") or {}
    protocol = str(node.get("protocol", "")).lower()
    name = urllib.parse.quote(str(node.get("name", "")))
    server, port = node.get("server", ""), node.get("port", 0)
    if protocol == "vless":
        query = urllib.parse.urlencode(
            {"encryption": "none", "security": "tls" if raw.get("tls") else "none", "type": raw.get("network", "tcp")}
        )
        return f"vless://{raw.get('uuid', '')}@{server}:{port}?{query}#{name}"
    if protocol == "vmess":
        payload = {
            "v": "2", "ps": node.get("name", ""), "add": server, "port": str(port),
            "id": raw.get("uuid", ""), "aid": str(raw.get("alterId", 0)), "net": raw.get("network", "tcp"),
            "type": "none", "tls": "tls" if raw.get("tls") else "",
        }
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        return f"vmess://{encoded}"
    if protocol == "trojan":
        query = urllib.parse.urlencode({"security": "tls", "type": raw.get("network", "tcp")})
        return f"trojan://{raw.get('password', '')}@{server}:{port}?{query}#{name}"
    if protocol == "hysteria2":
        query = urllib.parse.urlencode({"sni": raw.get("sni", "")})
        return f"hysteria2://{raw.get('password', '')}@{server}:{port}?{query}#{name}"
    if protocol == "ss":
        userinfo = base64.b64encode(f"{raw.get('cipher', 'aes-128-gcm')}:{raw.get('password', '')}".encode()).decode()
        return f"ss://{userinfo}@{server}:{port}#{name}"
    raise ValueError(f"不支持的协议: {protocol}")


def build_clash(nodes: list[dict]) -> str:
    proxies = []
    for node in nodes:
        raw = node.get("raw") or {}
        entry: dict = {
            "name": node.get("name", ""),
            "type": str(node.get("protocol", "")).lower(),
            "server": node.get("server", ""),
            "port": int(node.get("port", 0) or 0),
            "udp": True,
        }
        entry.update({k: v for k, v in raw.items() if k not in ("type", "server", "port", "name")})
        if "delay" in node and node["delay"] is not None:
            entry["delay"] = node["delay"]
        proxies.append(entry)
    config = {
        "proxies": proxies,
        "proxy-groups": [
            {"name": "🔀 自动选择", "type": "url-test", "proxies": [p["name"] for p in proxies]},
            {"name": "🚀 手动切换", "type": "select", "proxies": ["🔀 自动选择", *[p["name"] for p in proxies]]},
        ],
        "rules": ["MATCH,🚀 手动切换"],
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def build_v2ray(nodes: list[dict]) -> str:
    links = [_link(n) for n in nodes]
    return base64.b64encode("\n".join(links).encode()).decode()


def build_singbox(nodes: list[dict]) -> str:
    outbounds = []
    for node in nodes:
        raw = node.get("raw") or {}
        outbounds.append(
            {
                "type": str(node.get("protocol", "")).lower(),
                "tag": node.get("name", ""),
                "server": node.get("server", ""),
                "server_port": int(node.get("port", 0) or 0),
                **{k: v for k, v in raw.items() if k not in ("type", "server", "port")},
            }
        )
    config = {"outbounds": [{"type": "direct", "tag": "direct"}, *outbounds]}
    return json.dumps(config, ensure_ascii=False, indent=2)


def build(target: str, nodes: list[dict]) -> str:
    if target == "clash":
        return build_clash(nodes)
    if target == "v2ray":
        return build_v2ray(nodes)
    if target == "singbox":
        return build_singbox(nodes)
    raise ValueError(f"不支持的客户端类型: {target}")


def data_dir() -> str:
    return str(settings.data_dir)
