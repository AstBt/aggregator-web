# -*- coding: utf-8 -*-

import html
import re
import time
import urllib.parse
from dataclasses import replace

import utils
from config.models import TelegramChannelConfig, TelegramConfig
from crawl.base import Channel, register_channel
from crawl.extract import extract_subscribes
from crawl.helpers import merge_results
from crawl.models import ChannelResult, CrawlContext
from logger import logger
from origin import Origin


class TelegramChannel(Channel[TelegramConfig]):
    name = "telegram"

    def crawl(self, config: TelegramConfig, ctx: CrawlContext) -> ChannelResult:
        return crawl_telegram(config, ctx)


def crawl_telegram(config: TelegramConfig, ctx: CrawlContext) -> ChannelResult:
    starttime = time.time()
    jobs = []
    for name, item in config.channels.items():
        if not item.push_to:
            continue
        exclude = "|".join(x for x in (item.exclude, config.exclude) if x)
        jobs.append([name, replace(item, exclude=exclude), config.pages, ctx.include_nodes])
    results = utils.multi_thread_run(
        func=_crawl_channel, tasks=jobs, num_threads=ctx.num_threads, show_progress=ctx.display
    )
    result = merge_results(results)
    logger.info(
        f"[TelegramCrawl] found {len(result.items)} subscriptions and {len(result.nodes.uris)} node links "
        f"from {len(jobs)} channels, cost: {time.time() - starttime:.2f}s"
    )
    return result


def _previous_page(content: str, channel: str) -> str:
    for href in re.findall(r'''href=["']([^"']+)["']''', content):
        url = urllib.parse.urljoin("https://t.me", html.unescape(href))
        parsed = urllib.parse.urlsplit(url)
        before = urllib.parse.parse_qs(parsed.query).get("before", [""])[0]
        if parsed.hostname == "t.me" and parsed.path == f"/s/{channel}" and before.isdigit():
            return url
    return ""


def _crawl_channel(channel: str, config: TelegramChannelConfig, pages: int, include_nodes: bool) -> ChannelResult:
    result = ChannelResult()
    url, seen, fetched = f"https://t.me/s/{channel}", set(), 0
    for _ in range(max(1, pages)):
        if not url or url in seen:
            break
        seen.add(url)
        content = utils.http_get(url=url, retry=2, timeout=12)
        if not content:
            logger.warning(f"[TelegramCrawl] channel request failed: {channel}, page={fetched + 1}")
            break
        fetched += 1
        result.merge(extract_subscribes(
            content=content,
            push_to=config.push_to,
            include=config.include,
            exclude=config.exclude,
            source=Origin.TELEGRAM.name,
            task=config.task,
            reversed=True,
            include_nodes=include_nodes,
        ))
        url = _previous_page(content, channel)
    logger.info(f"[TelegramCrawl] channel={channel}, pages={fetched}, subscriptions={len(result.items)}, nodes={len(result.nodes.uris)}")
    return result


register_channel(TelegramChannel())
