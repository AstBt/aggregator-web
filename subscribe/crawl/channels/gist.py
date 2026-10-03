# -*- coding: utf-8 -*-

import json
import os
import re
import time
import urllib.parse

import utils
from config.models import GistConfig
from crawl.base import Channel, register_channel
from crawl.channels.github import intercept
from crawl.extract import extract_subscribes
from crawl.models import ChannelResult, CrawlContext
from logger import logger
from origin import Origin

GIST_API = "https://api.github.com"
GIST_SEARCH = "https://gist.github.com/search"
# 搜索结果页同时存在完整链接与相对路径 href(单/双引号)两种形式,取第二组为 gist id
GIST_PATTERN = re.compile(r"""href=['"]/?([^/'"\s>#?]+)/([0-9a-f]{20,})""")


def gist_headers() -> dict[str, str]:
    """GH_TOKEN(任意 scope)或 PUSH_TOKEN(gist scope)均可读取公开 gist,无需额外权限"""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": utils.USER_AGENT}
    token = utils.trim(os.environ.get("GH_TOKEN", "") or os.environ.get("PUSH_TOKEN", ""))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_gists(cookie: str, patterns: list[tuple[str, ...]], pages: int, max_gists: int) -> list[dict]:
    """通过 gist 网页搜索(需登录态 cookie,服务端渲染)按模式发现 gist ID"""
    headers = {
        "User-Agent": utils.USER_AGENT,
        "Cookie": f"user_session={cookie}",
        "Accept": "text/html,application/xhtml+xml",
    }
    ids, seen = [], set()
    for pattern in patterns:
        query = utils.trim("+".join(f'"{word}"' for word in pattern))
        if not query:
            continue
        for page in range(1, max(1, pages) + 1):
            url = f"{GIST_SEARCH}?q={urllib.parse.quote(query, safe='')}&p={page}"
            content = utils.http_get(url=url, headers=headers, timeout=20)
            if utils.isblank(content):
                break
            found = GIST_PATTERN.findall(content)
            if not found:
                break
            for pair in found:
                gid = pair[-1] if isinstance(pair, tuple) else pair
                if gid and gid not in seen:
                    seen.add(gid)
                    ids.append(gid)
                    if len(ids) >= max_gists:
                        return _fetch_by_ids(headers=gist_headers(), ids=ids)
    return _fetch_by_ids(headers=gist_headers(), ids=ids)


def _fetch_by_ids(headers: dict[str, str], ids: list[str]) -> list[dict]:
    gists = []
    for gid in ids:
        content = utils.http_get(url=f"{GIST_API}/gists/{gid}", headers=headers, timeout=15)
        if utils.isblank(content):
            continue
        try:
            item = json.loads(content)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("id"):
            gists.append(item)
    return gists


def list_public_gists(headers: dict[str, str], count: int, exclude_repos: list[str] | None = None) -> list[dict]:
    """拉取最近的公开 gist(GitHub 无 gist 搜索 API,公开时间线是可行的发现面)"""
    url = f"{GIST_API}/gists/public?per_page=100"
    gists, seen = [], set()
    for _ in range(max(1, count // 100 + 1)):
        content = utils.http_get(url=url, headers=headers, timeout=20)
        if utils.isblank(content):
            break
        try:
            items = json.loads(content)
        except Exception:
            logger.error("[GistCrawl] cannot parse gists list from github")
            break
        if not isinstance(items, list) or not items:
            break
        for item in items:
            gid = item.get("id", "")
            if not gid or gid in seen:
                continue
            seen.add(gid)
            gists.append(item)
            if len(gists) >= count:
                return gists
        # 翻页: 取列表最后一条的 updated_at 作为下次 since(GitHub 分页游标)
        since = items[-1].get("updated_at", "")
        if not since:
            break
        url = f"{GIST_API}/gists/public?per_page=100&since={utils.trim(since)}"
        time.sleep(0.2)
    return gists


def fetch_gist_content(gist: dict, headers: dict[str, str], max_size: int) -> str:
    """取 gist 内全部文件的明文内容,超过 max_size 的文件跳过"""
    files = gist.get("files") or {}
    parts = []
    for file in files.values():
        url, truncated = file.get("raw_url", ""), file.get("truncated", False)
        size = int(file.get("size", 0) or 0)
        if not url or truncated or size <= 0 or size > max_size:
            continue
        content = utils.http_get(url=url, headers=headers, timeout=15)
        if content:
            parts.append(content)
    return "\n".join(parts)


def _extract_gist(
    gist: dict, headers: dict[str, str], config: GistConfig, include_nodes: bool
) -> ChannelResult | None:
    owner = (gist.get("owner") or {}).get("login", "")
    if intercept(text=f"{owner}/", excludes=config.exclude_owners):
        return None
    content = fetch_gist_content(gist=gist, headers=headers, max_size=config.max_filesize)
    if not content:
        return None
    return extract_subscribes(
        content=content,
        push_to=config.push_to,
        include=config.include,
        exclude=config.exclude,
        source=Origin.GIST.name,
        task=config.task,
        include_nodes=include_nodes,
    )


def crawl_gist(config: GistConfig, ctx: CrawlContext) -> ChannelResult:
    headers = gist_headers()
    starttime = time.time()

    cookie = utils.trim(os.environ.get("GH_COOKIE", ""))
    if cookie and not utils.trim(os.environ.get("GH_TOKEN", "")) and not utils.trim(os.environ.get("PUSH_TOKEN", "")):
        logger.error("[GistCrawl] cannot start crawl from gist because token is missing")
        return ChannelResult()
    if not cookie and utils.trim(os.environ.get("GH_TOKEN", "")) == "" and utils.trim(os.environ.get("PUSH_TOKEN", "")) == "":
        logger.error("[GistCrawl] cannot start crawl from gist because token is missing")
        return ChannelResult()

    patterns = [tuple(p.split()) for p in (config.patterns or []) if utils.trim(p)]
    patterns = patterns or [("/api/v1/client/subscribe?token=",), ("/link/", "?sub=1")]
    if cookie:
        gists = search_gists(cookie=cookie, patterns=patterns, pages=config.pages, max_gists=config.max_gists)
        mode = "search"
    else:
        gists = list_public_gists(headers=headers, count=config.max_gists)
        mode = "timeline"
    if not gists:
        logger.error(f"[GistCrawl] cannot fetch gists from github, mode: {mode}")
        return ChannelResult()

    params = [[gist, headers, config, ctx.include_nodes] for gist in gists]
    results = utils.multi_thread_run(func=_extract_gist, tasks=params, num_threads=ctx.num_threads)
    result, matched = ChannelResult(), 0
    for single in results:
        if single and (single.items or single.nodes.uris):
            matched += 1
            result.merge(single)
    logger.info(
        f"[GistCrawl] found {len(result.items)} subscriptions in {matched}/{len(gists)} gists, mode: {mode}, cost: {time.time() - starttime:.2f}s"
    )
    return result


class GistChannel(Channel[GistConfig]):
    name = "gist"

    def crawl(self, config: GistConfig, ctx: CrawlContext) -> ChannelResult:
        return crawl_gist(config, ctx)


register_channel(GistChannel())
