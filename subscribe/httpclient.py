# -*- coding: utf-8 -*-

import ipaddress
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from http.client import HTTPException

from logger import logger

_PROXY_ERRORS = {403, 429, 500, 502, 503, 504}
_PROXY_ENV = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")


def is_loopback(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def proxy_address(url: str) -> str:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    address = os.environ.get(f"{scheme}_proxy") or os.environ.get(f"{scheme.upper()}_PROXY", "")
    return address if address.startswith(("http://", "https://")) else ""


@lru_cache(maxsize=16)
def _opener(proxy: str, context: ssl.SSLContext | None):
    proxies = {"http": proxy, "https": proxy} if proxy else {}
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=context),
    )


def open_url(
    request: urllib.request.Request | str,
    timeout: float = 10,
    context: ssl.SSLContext | None = None,
    proxy: str | None = None,
    direct: bool = False,
    fallback: bool = True,
):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    address = "" if direct or is_loopback(url) else (proxy if proxy is not None else proxy_address(url))
    if address and not address.startswith(("http://", "https://")):
        raise ValueError("proxy address must use http:// or https://")

    routes = (address, "") if address and fallback else (address,)
    for index, route in enumerate(routes):
        if isinstance(request, urllib.request.Request):
            attempt = urllib.request.Request(
                request.full_url,
                data=request.data,
                headers=dict(request.header_items()),
                method=request.get_method(),
            )
        else:
            attempt = request
        try:
            return _opener(route, context).open(attempt, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if index + 1 == len(routes) or exc.code not in _PROXY_ERRORS:
                raise
            exc.close()
        except (urllib.error.URLError, OSError, HTTPException):
            if index + 1 == len(routes):
                raise
    raise RuntimeError("HTTP request has no route")


def configure_proxy(enable: bool, address: str, test_url: str, context: ssl.SSLContext | None = None) -> str:
    if not enable:
        return ""
    if not address.startswith(("http://", "https://")) or not urllib.parse.urlsplit(address).hostname:
        raise ValueError("enabled local proxy requires an http(s) address")

    # A denied probe proves connectivity, not permission to access that endpoint.
    probes = list(dict.fromkeys([test_url, "https://github.com/"]))
    for url in probes:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with open_url(request, timeout=6, context=context, proxy=address, fallback=False) as response:
                available = 200 <= response.status < 400
        except urllib.error.HTTPError as exc:
            available = exc.code in {401, 403, 429}
            if available:
                logger.warning(f"[Proxy] probe endpoint returned HTTP {exc.code}; proxy transport is reachable")
            exc.close()
        except (urllib.error.URLError, OSError, HTTPException):
            available = False
        if available:
            for name in _PROXY_ENV:
                os.environ[name] = address
            bypass = os.environ.get("no_proxy") or os.environ.get("NO_PROXY", "")
            bypass = ",".join(dict.fromkeys(x.strip() for x in bypass.split(",") + ["localhost", "127.0.0.1", "::1"] if x.strip()))
            os.environ["no_proxy"] = os.environ["NO_PROXY"] = bypass
            logger.info("[Proxy] configured proxy reachable; external HTTP prefers proxy with direct fallback")
            return address

    for name in _PROXY_ENV:
        os.environ.pop(name, None)
    logger.warning("[Proxy] configured proxy probes failed; external HTTP falls back to direct connections")
    return ""
