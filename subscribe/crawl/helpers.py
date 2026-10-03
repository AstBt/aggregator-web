# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import random
import re
import socket
import ssl
import string
import time
import urllib
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPResponse

import airport
import httpclient
import utils
from config.models import StorageItem
from crawl.channels.page import PageChannel
from crawl.models import ChannelResult, CrawlContext
from logger import logger
from origin import Origin
from push import PushTo

SEPARATOR = "-"


_REJECT_CONTENT_TYPE_PREFIXES = (
    "video/",
    "audio/",
    "image/",
    "font/",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "application/zip",
    "application/x-zip",
    "application/gzip",
    "application/x-gzip",
    "application/x-tar",
    "application/x-rar",
    "application/pdf",
    "application/x-msdownload",
    "application/vnd.",
)

_REJECT_DISPOSITION_EXT = (
    ".zip",
    ".iso",
    ".exe",
    ".mp4",
    ".mkv",
    ".avi",
    ".tar",
    ".tgz",
    ".gz",
    ".7z",
    ".rar",
    ".bin",
    ".img",
    ".dmg",
    ".apk",
    ".msi",
    ".pdf",
    ".torrent",
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
    ".ico",
)

_VALIDATE_UNIDENTIFIED_BYTES = 64 * 1024
_VALIDATE_CHUNK_SIZE = 8 * 1024
_VALIDATE_SNIFF_DEADLINE = 8
_VALIDATE_DEADLINE = 12
_VALIDATE_CONNECT_TIMEOUT = 10


def merge_results(results: list[ChannelResult | None]) -> ChannelResult:
    merged = ChannelResult()
    for item in results or []:
        merged.merge(item)
    return merged


def fetch_jobs(jobs: list[PageChannel] | None, ctx: CrawlContext) -> ChannelResult:
    if not isinstance(ctx, CrawlContext):
        return ChannelResult()
    jobs = [job for job in (jobs or []) if isinstance(job, PageChannel)]
    if not jobs:
        return ChannelResult()
    if len(jobs) == 1:
        return jobs[0].fetch(ctx)
    results = utils.multi_thread_run(
        func=_fetch_job,
        tasks=[[job, ctx] for job in jobs],
        num_threads=ctx.num_threads,
        show_progress=ctx.display,
    )
    return merge_results(results)


def _fetch_job(job: PageChannel, ctx: CrawlContext) -> ChannelResult:
    if not isinstance(job, PageChannel) or not isinstance(ctx, CrawlContext):
        return ChannelResult()
    return job.fetch(ctx)


def is_reachable(url: str, timeout: float = 5, retry: int = 2) -> bool:
    url = utils.trim(url)
    if not url:
        return False
    timeout = max(1.0, float(timeout))
    retry = max(1, int(retry))
    headers = utils.DEFAULT_HTTP_HEADERS
    for attempt in range(retry):
        try:
            request = urllib.request.Request(url=url, headers=headers)
            with httpclient.open_url(request, timeout=timeout, context=utils.CTX):
                return True
        except urllib.error.HTTPError:
            return True
        except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError, OSError):
            if attempt + 1 >= retry:
                return False
        except Exception:
            return False
    return False


def load_records(pushtool: PushTo | None, item: StorageItem | None) -> dict[str, object]:
    if not isinstance(pushtool, PushTo) or not isinstance(item, StorageItem) or not pushtool.validate(item=item):
        return {}
    try:
        url = pushtool.raw_url(item=item) or ""
        content = ""
        if not url.startswith(utils.FILEPATH_PROTOCAL):
            content = utils.http_get(url=url)
        else:
            file = url[len(utils.FILEPATH_PROTOCAL) :]
            if os.path.exists(file) and os.path.isfile(file):
                with open(file, "r", encoding="utf8") as reader:
                    content = reader.read()
        if utils.isblank(content):
            return {}
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.error("[CrawlError] load old subscriptions from remote error")
        return {}


def save_records(pushtool: PushTo | None, item: StorageItem | None, records: dict[str, object] | None) -> bool:
    if (
        not isinstance(pushtool, PushTo)
        or not isinstance(item, StorageItem)
        or not records
        or not pushtool.validate(item=item)
    ):
        return False
    try:
        return pushtool.push_to(content=json.dumps(records), item=item, group="crawl")
    except Exception:
        logger.error("[CrawlError] save subscriptions failed")
        return False


def remark(source: dict[str, object], defeat: int = 0, discovered: bool = True) -> None:
    if not source or type(source) != dict or type(defeat) != int or defeat < 0 or type(discovered) != bool:
        return

    source["defeat"] = defeat
    source["discovered"] = discovered
    if utils.isblank(source.get("origin", "")):
        source["origin"] = Origin.TEMPORARY.name


def check_status(
    url: str,
    retry: int = 2,
    remain: float = 0,
    spare_time: float = 0,
    tolerance: float = 0,
    connectable: bool = True,
    proxy: str = "",
) -> tuple[bool, bool]:
    """
    url: subscription link
    retry: number of retries
    remain: minimum remaining traffic flow
    spare_time: minimum remaining time
    tolerance: waiting time after expiration
    proxy: preferred local proxy; transport failures fall back to direct connections

    Returns:
        tuple[bool, bool]: (available, expired)
        - First bool: whether the subscription is available
        - Second bool: whether the subscription has expired
    """
    if not url or retry <= 0:
        return False, connectable
    if utils.is_suspicious_url(url):
        logger.debug(f"[Validate] skip suspicious url: {utils.mask(url)}")
        return False, True

    for attempt in range(retry):
        response = None
        try:
            deadline = time.monotonic() + _VALIDATE_DEADLINE
            request = urllib.request.Request(
                url=url, headers={"User-Agent": f"{utils.USER_AGENT}; Clash.Meta; Mihomo; Shadowrocket;"}
            )
            response = httpclient.open_url(
                request, timeout=_VALIDATE_CONNECT_TIMEOUT, context=utils.CTX, proxy=proxy or None
            )
            if response.getcode() != 200:
                return False, False
            if _should_reject_response(response):
                return False, True
            subscription = response.getheader("subscription-userinfo")
            raw = _read_subscription_body(response, deadline=deadline)
            if raw is None:
                return False, False
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                return False, True
            if len(content) < 32:
                return False, False
            if utils.isb64encode(content) or _looks_like_subscription(raw) == "yes":
                return is_expired(header=subscription, remain=remain, spare_time=spare_time, tolerance=tolerance)
            lines = [line for line in content.splitlines() if line.strip()]
            if lines and all(airport.AirPort.check_protocol(line) for line in lines):
                return is_expired(header=subscription, remain=remain, spare_time=spare_time, tolerance=tolerance)
            return False, True
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                invalid_token = "token is error" in exc.read(4096).decode("utf8", errors="replace")
            finally:
                exc.close()
            if code == 404 or invalid_token:
                return False, True
            if code not in {403, 429, 500, 502, 503, 504} or attempt + 1 == retry:
                return False, False
        except (urllib.error.URLError, OSError):
            if attempt + 1 == retry:
                return False, False
        except Exception as exc:
            logger.debug(f"[Validate] unexpected error for {utils.mask(url)}: {exc}")
            return False, False
        finally:
            if response is not None:
                response.close()
    return False, False


def is_expired(header: str, remain: float = 0, spare_time: float = 0, tolerance: float = 0) -> tuple[bool, bool]:
    if utils.isblank(header):
        return True, False

    remain, spare_time, tolerance = (
        max(0, remain),
        max(spare_time, 0),
        max(tolerance, 0),
    )
    try:
        numeric = {}
        for field in header.split(";"):
            key, separator, value = field.partition("=")
            key, value = key.strip(), value.strip()
            if separator and key in {"upload", "download", "total", "expire"} and value:
                numeric[key] = int(value)
        upload, download, total = (numeric.get(key, 0) for key in ("upload", "download", "total"))
        expire = numeric.get("expire")

        # 剩余流量大于 ${remain} GB 并且未过期则返回 True，否则返回 False
        flag = total - (upload + download) > remain * pow(1024, 3) and (
            expire is None or expire - time.time() > spare_time * 3600
        )
        expired = False if flag else (expire is not None and (expire + tolerance * 3600) <= time.time())
        return flag, expired
    except:
        return True, False


def _should_reject_response(response: HTTPResponse | None) -> bool:
    """响应头检查 - 明显不是订阅"""
    if response is None:
        return False
    ctype = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
    if ctype:
        for prefix in _REJECT_CONTENT_TYPE_PREFIXES:
            if ctype.startswith(prefix):
                return True

    disposition = response.getheader("Content-Disposition") or ""
    if disposition:
        m = re.search(r"filename\*?=(?:UTF-8''|\"|')?([^\";]+)", disposition, re.I)
        if m:
            name = urllib.parse.unquote(m.group(1).strip().strip("\"'")).lower()
            if name.endswith(_REJECT_DISPOSITION_EXT):
                return True

    return False


def _read_subscription_body(response: HTTPResponse | None, deadline: float | None = None) -> bytes | None:
    """Sniff a subscription from the response body and stop as soon as it is confirmed"""
    if response is None:
        return None
    start = time.monotonic()
    buf = bytearray()
    limit = _VALIDATE_UNIDENTIFIED_BYTES
    verdict = "maybe"

    while len(buf) < limit:
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            try:
                response.close()
            except Exception:
                pass
            return None
        if verdict != "yes" and (now - start) > _VALIDATE_SNIFF_DEADLINE:
            try:
                response.close()
            except Exception:
                pass
            return None

        to_read = min(_VALIDATE_CHUNK_SIZE, limit - len(buf))
        try:
            chunk = response.read(to_read)
        except (socket.timeout, TimeoutError, OSError):
            try:
                response.close()
            except Exception:
                pass
            return None

        if not chunk:
            break

        buf.extend(chunk)

        if verdict != "yes":
            verdict = _looks_like_subscription(bytes(buf))
            if verdict == "no":
                try:
                    response.close()
                except Exception:
                    pass
                return None
            if verdict == "yes":
                try:
                    response.close()
                except Exception:
                    pass
                return bytes(buf)

    if verdict != "yes" and len(buf) >= _VALIDATE_UNIDENTIFIED_BYTES:
        try:
            extra = response.read(1)
        except Exception:
            extra = b""
        if extra:
            try:
                response.close()
            except Exception:
                pass
            return None

    return bytes(buf)


def _looks_like_subscription(data: bytes) -> str:
    """内容嗅探 - 返回 'yes' / 'no' / 'maybe'"""
    if not data:
        return "maybe"

    sample = data[:8192]
    if b"\x00" in sample:
        return "no"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "no"

    sample_text = text.lstrip("﻿ \t\r\n")
    if not sample_text:
        return "maybe"

    head = sample_text[:64].lower()
    if head.startswith(("<!doctype", "<html", "<?xml", "<head", "<body")):
        return "no"

    # Clash YAML
    if re.search(
        r"^(proxies|proxy-groups|port|mixed-port|socks-port|redir-port|tproxy-port|allow-lan|mode|dns|rules)\s*:",
        sample_text,
        re.M | re.I,
    ):
        return "yes"

    # Surge / Loon / Quantumult
    if re.search(r"^\[(?:Proxy|Proxy Group|Rule|General|Replica)\]", sample_text, re.M | re.I):
        return "yes"
    if "MANAGED-CONFIG" in sample_text[:500].upper() or sample_text.lstrip().startswith("#!"):
        return "yes"

    # sing-box JSON
    stripped = sample_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        if re.search(r'"(outbounds|inbounds|proxies|server|protocol|dns)"', sample_text):
            return "yes"
        return "maybe"

    # 协议链接，机场订阅常见
    if re.search(r"(?im)^(vmess|trojan|ss|ssr|vless|hysteria2?|tuic|snell|anytls|socks5)://", sample_text):
        return "yes"

    # base64，允许换行
    compact = re.sub(r"\s+", "", sample_text[:4096])
    if len(compact) >= 32 and re.match(r"^[A-Za-z0-9+/=]+$", compact):
        return "yes"

    # 纯注释开头，机场订阅常见前言
    lines = [ln.strip() for ln in sample_text.splitlines() if ln.strip()]
    if lines and all(ln.startswith("#") or ln.startswith("//") for ln in lines):
        return "maybe"

    return "maybe"


def is_available(url: str, retry: int = 2, remain: float = 0, spare_time: float = 0) -> bool:
    available, _ = check_status(url=url, retry=retry, remain=remain, spare_time=spare_time)
    return available


def naming_task(url: str) -> str:
    prefix = utils.extract_domain(url=url).replace(".", "") + SEPARATOR
    return prefix + "".join(random.sample(string.digits + string.ascii_lowercase, random.randint(3, 5)))
