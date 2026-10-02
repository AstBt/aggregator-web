#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Generate dynamic HTTP/SOCKS proxy nodes from CLI options"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import secrets
import string
import sys
from dataclasses import dataclass

SCHEMES = ("socks5", "socks5h", "http", "https")
FORMATS = ("uri", "clash")
NAMING_MODES = ("sid", "index", "none")
SID_CHARS = string.ascii_letters + string.digits
KEYWORD_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
POSITIVE_INT = re.compile(r"^[1-9]\d*$")
ILLEGAL_CHARS = set(":@#/?%")
ISO_CODES = frozenset("""
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
    BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
    CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
    DE DJ DK DM DO DZ
    EC EE EG EH ER ES ET
    FI FJ FK FM FO FR
    GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
    HK HM HN HR HT HU
    ID IE IL IM IN IO IQ IR IS IT
    JE JM JO JP
    KE KG KH KI KM KN KP KR KW KY KZ
    LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
    NA NC NE NF NG NI NL NO NP NR NU NZ
    OM
    PA PE PF PG PH PK PL PM PN PR PS PT PW PY
    QA
    RE RO RS RU RW
    SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
    TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
    UA UG UM US UY UZ
    VA VC VE VG VI VN VU
    WF WS
    XK
    YE YT
    ZA ZM ZW
    """.split())


class ValidationError(ValueError):
    pass


@dataclass
class Config:
    scheme: str
    username: str
    password: str
    host: str
    port: int
    count: int
    region_key: str
    country: str
    state_key: str
    state: str
    session_key: str
    sid_length: int
    duration_key: str
    duration: int
    naming_mode: str
    output_format: str
    output_path: str


def trim(value: object | None) -> str:
    return "" if value is None else str(value).strip()


def require_text(value: object | None, name: str) -> str:
    text = trim(value)
    if not text:
        raise ValidationError(f"{name} is required")
    if any(ch.isspace() for ch in text):
        raise ValidationError(f"{name} must not contain whitespace")
    if any(ch in ILLEGAL_CHARS for ch in text):
        raise ValidationError(f"{name} contains illegal character")
    return text


def require_keyword(value: object | None, name: str, required: bool = True) -> str:
    text = trim(value)
    if not text:
        if required:
            raise ValidationError(f"{name} is required")
        return ""
    if any(ch.isspace() for ch in text):
        raise ValidationError(f"{name} must not contain whitespace")
    if not KEYWORD_PATTERN.fullmatch(text):
        raise ValidationError(f"{name} may contain only letters, digits, '-' and '_'")
    return text


def require_integer(value: object | None, name: str, maximum: int | None = None) -> int:
    text = trim(value)
    if not POSITIVE_INT.fullmatch(text):
        raise ValidationError(f"{name} must be an integer > 0")
    number = int(text)
    if maximum is not None and number > maximum:
        raise ValidationError(f"{name} must be <= {maximum}")
    return number


def require_host(value: object | None) -> str:
    host = require_text(value, "host")
    try:
        ipaddress.IPv4Address(host)
        return host
    except ValueError:
        pass
    hostname = host[:-1] if host.endswith(".") else host
    if not hostname or len(hostname) > 253:
        raise ValidationError("host must be a domain or IPv4 address")
    labels = hostname.split(".")
    if not all(DOMAIN_LABEL.fullmatch(label) for label in labels):
        raise ValidationError("host must be a domain or IPv4 address")
    return host


def require_country(value: object | None) -> str:
    text = trim(value)
    if not text:
        return ""
    country = text.upper()
    if country not in ISO_CODES:
        raise ValidationError("country must be an ISO 3166-1 alpha-2 code")
    return country


def require_choice(value: object | None, name: str, options: tuple[str, ...], default: str) -> str:
    text = trim(value).lower()
    if not text:
        return default
    if text not in options:
        raise ValidationError(f"{name} must be one of {', '.join(options)}")
    return text


def generate_sids(count: int, length: int) -> list[str]:
    capacity = len(SID_CHARS) ** length
    if count > capacity:
        raise ValidationError(f"count {count} exceeds unique sid space {capacity} for sid-length {length}")
    randomizer = secrets.SystemRandom()
    if length == 1:
        return randomizer.sample(list(SID_CHARS), count)
    seen: set[str] = set()
    sids: list[str] = []
    while len(sids) < count:
        sid = "".join(randomizer.choice(SID_CHARS) for _ in range(length))
        if sid in seen:
            continue
        seen.add(sid)
        sids.append(sid)
    return sids


def build_username(config: Config, sid: str) -> str:
    parts = [config.username]
    if config.country:
        parts.extend((config.region_key, config.country))
        if config.state:
            parts.extend((config.state_key, config.state))
    parts.extend((config.session_key, sid, config.duration_key, str(config.duration)))
    return "-".join(parts)


def build_node_name(config: Config, sid: str, index: int, index_width: int) -> str:
    if config.naming_mode == "none":
        return ""
    suffix = sid if config.naming_mode == "sid" else f"{index:0{index_width}d}"
    return f"{config.country}-{suffix}" if config.country else suffix


def format_uri(config: Config, username: str, node_name: str) -> str:
    uri = f"{config.scheme}://{username}:{config.password}@{config.host}:{config.port}"
    return f"{uri}#{node_name}" if node_name else uri


def format_clash(config: Config, username: str, node_name: str) -> str:
    proxy_type = "http" if config.scheme in ("http", "https") else "socks5"
    proxy = {
        "name": node_name,
        "type": proxy_type,
        "server": config.host,
        "port": config.port,
        "username": username,
        "password": config.password,
    }
    if config.scheme in ("socks5", "socks5h"):
        proxy["udp"] = True
        proxy["tls"] = True
        proxy["skip-cert-verify"] = False
    elif config.scheme == "https":
        proxy["tls"] = True
        proxy["skip-cert-verify"] = False
    return json.dumps(proxy, ensure_ascii=False, separators=(",", ":"))


def parse_config(args: argparse.Namespace) -> Config:
    scheme = require_choice(args.scheme, "scheme", SCHEMES, "socks5")
    username = require_text(args.username, "username")
    password = require_text(args.password, "password")
    host = require_host(args.host)
    port = require_integer(args.port, "port", maximum=65535)
    count = require_integer(args.count, "count")
    region_key = require_keyword(args.region_key, "region-key")
    country = require_country(args.country)
    state_key = require_keyword(args.state_key, "state-key", required=False)
    state = require_keyword(args.state, "state", required=False)
    session_key = require_keyword(args.session_key, "session-key")
    sid_length = require_integer(args.sid_length, "sid-length", maximum=64)
    duration_key = require_keyword(args.duration_key, "duration-key")
    duration = require_integer(args.duration, "duration")
    naming_mode = require_choice(args.naming, "naming", NAMING_MODES, "sid")
    output_format = require_choice(args.format, "format", FORMATS, "uri")
    output_path = trim(args.output)

    if bool(state_key) != bool(state):
        raise ValidationError("state-key and state must be provided together")
    if (state_key or state) and not country:
        raise ValidationError("state requires country")
    if naming_mode == "none" and output_format != "uri":
        raise ValidationError("naming=none is only supported when format=uri")

    return Config(
        scheme=scheme,
        username=username,
        password=password,
        host=host,
        port=port,
        count=count,
        region_key=region_key,
        country=country,
        state_key=state_key,
        state=state,
        session_key=session_key,
        sid_length=sid_length,
        duration_key=duration_key,
        duration=duration,
        naming_mode=naming_mode,
        output_format=output_format,
        output_path=output_path,
    )


def generate_nodes(config: Config) -> list[str]:
    sids = generate_sids(config.count, config.sid_length)
    index_width = len(str(config.count))
    nodes: list[str] = []
    for index, sid in enumerate(sids, start=1):
        username = build_username(config, sid)
        node_name = build_node_name(config, sid, index, index_width)
        if config.output_format == "clash":
            nodes.append(f"  - {format_clash(config, username, node_name)}")
        else:
            nodes.append(format_uri(config, username, node_name))
    if config.output_format == "clash":
        return ["proxies:", *nodes]
    return nodes


def write_output(nodes: list[str], output_path: str) -> None:
    content = "\n".join(nodes)
    if content:
        content += "\n"
    if not output_path:
        sys.stdout.write(content)
        return
    path = os.path.abspath(output_path)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        raise ValidationError(f"output directory not found: {directory}")
    with open(path, "w", encoding="utf-8", newline="\n") as output_file:
        output_file.write(content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate dynamic HTTP/SOCKS proxy nodes",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "example:\n"
            "  python proxies-gen.py --username alice --password secret --host gate.example.com --port 1080 --count 10 "
            "--session-key sid --sid-length 8 --duration-key t --country US --state-key st --state california"
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--scheme", default="socks5", help="socks5, socks5h, http or https")
    parser.add_argument("--username", required=True, help="base username")
    parser.add_argument("--password", required=True, help="password")
    parser.add_argument("--host", required=True, help="domain or IPv4 address")
    parser.add_argument("--port", required=True, help="port, 1-65535")
    parser.add_argument("--count", required=True, help="number of nodes")
    parser.add_argument("--region-key", default="region", help="region keyword, default: region")
    parser.add_argument("--country", default="", help="ISO 3166-1 alpha-2 country code")
    parser.add_argument("--state-key", default="", help="state or city keyword, e.g. st")
    parser.add_argument("--state", default="", help="state or city name")
    parser.add_argument("--session-key", required=True, help="session keyword, e.g. sid")
    parser.add_argument("--sid-length", required=True, help="random sid length")
    parser.add_argument("--duration-key", required=True, help="session duration keyword, e.g. t")
    parser.add_argument("--duration", default="5", help="session duration, default: 5")
    parser.add_argument("--naming", default="sid", help="node name style: sid, index or none, none only for uri")
    parser.add_argument("--format", default="uri", help="uri or clash")
    parser.add_argument("--output", default="", help="output file, default: stdout")
    return parser


def main() -> None:
    parser = build_parser()
    try:
        config = parse_config(parser.parse_args())
        write_output(generate_nodes(config), config.output_path)
    except ValidationError as error:
        parser.error(str(error))
    except OSError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
