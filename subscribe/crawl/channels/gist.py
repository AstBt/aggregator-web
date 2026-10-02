# -*- coding: utf-8 -*-

import json
import os
import time

import utils
from config.models import GistConfig
from crawl.base import Channel, register_channel
from crawl.channels.github import intercept
from crawl.extract import extract_subscribes
from crawl.models import ChannelResult, CrawlContext
from logger import logger
from origin import Origin

GIST_API = "https://api.github.com"


def gist_headers() -> dict[str, str]:
    """GH_TOKEN(任意 scope)或 PUSH_TOKEN(gist scope)均可读取公开 gist,无需额外权限"""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": utils.USER_AGENT}
    token = utils.trim(os.environ.get("GH_TOKEN", "") or os.environ.get("PUSH_TOKEN", ""))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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


def crawl_gist(config: GistConfig, ctx: CrawlContext) -> ChannelResult:
    headers = gist_headers()
    starttime = time.time()
    gists = list_public_gists(headers=headers, count=config.max_gists)
    if not gists:
        logger.error("[GistCrawl] cannot fetch public gists from github")
        return ChannelResult()

    result = ChannelResult()
    matched = 0
    for gist in gists:
        owner = (gist.get("owner") or {}).get("login", "")
        slug = f"{owner}/{gist.get('id', '')}"
        if intercept(text=f"{owner}/", excludes=config.exclude_owners):
            continue
        content = fetch_gist_content(gist=gist, headers=headers, max_size=config.max_filesize)
        if not content:
            continue
        single = extract_subscribes(
            content=content,
            push_to=config.push_to,
            include=config.include,
            exclude=config.exclude,
            source=Origin.GIST.name,
            task=config.task,
            include_nodes=ctx.include_nodes,
        )
        if single.items or single.nodes.uris:
            matched += 1
            result.merge(single)
    logger.info(
        f"[GistCrawl] found {len(result.items)} subscriptions in {matched}/{len(gists)} gists, cost: {time.time() - starttime:.2f}s"
    )
    return result


class GistChannel(Channel[GistConfig]):
    name = "gist"

    def crawl(self, config: GistConfig, ctx: CrawlContext) -> ChannelResult:
        if utils.isblank(os.environ.get("GH_TOKEN", "")) and utils.isblank(os.environ.get("PUSH_TOKEN", "")):
            logger.error("[GistCrawl] cannot start crawl from gist because token is missing")
            return ChannelResult()
        return crawl_gist(config, ctx)


register_channel(GistChannel())
