# -*- coding: utf-8 -*-

import itertools
import json
import os
import re
import time
import traceback
import urllib.parse

import utils
from config.models import GithubConfig
from crawl.base import Channel, register_channel
from crawl.channels.page import PageChannel
from crawl.models import ChannelResult, CrawlContext
from logger import logger
from origin import Origin

# 内置搜索模式:每项是一个词组元组,词组之间为 AND 关系(均按字面量匹配)
# 可通过配置 crawl.github.patterns 覆盖,格式为字符串列表,空格分隔多个词组
DEFAULT_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("/api/v1/client/subscribe?token=",),  # v2board 面板订阅
    ("subscribe?token=",),  # 其他面板路径的带 token 订阅
    ("/link/", "?sub=1"),  # sspanel / Sub-Store 风格短链订阅
)


def build_query(pattern: tuple[str, ...], regex: bool = False) -> str:
    """把词组元组转为 GitHub 搜索的 q 参数(字面量匹配, AND 组合)"""
    if regex:
        # 网页版代码搜索使用正则语法
        words = [re.escape(word) for word in pattern]
        return "+".join("%22" + word + "%22" for word in words)
    return "+".join(urllib.parse.quote(f'"{word}"', safe="") for word in pattern)


class GithubChannel(Channel[GithubConfig]):
    name = "github"

    def crawl(self, config: GithubConfig, ctx: CrawlContext) -> ChannelResult:
        return crawl_github(config, ctx)


def intercept(text: str, excludes: list[str] | None = None) -> bool:
    if not excludes:
        return False
    for regex in excludes:
        try:
            if re.search(regex, text, flags=re.I):
                return True
        except Exception:
            logger.error(f"[GithubRepoIntercept] invalid regex pattern: {regex}")
    return False


def paging(start: int, end: int, peer_page: int) -> list[int]:
    if start > end or peer_page <= 0:
        return []
    pages = []
    for i in range(start, end + 1, peer_page):
        pages.append(i // peer_page + 1)
    return pages


def search_github(page: int, cookie: str, searchtype: str, sortedby: str, query: str = "") -> str:
    if page <= 0 or utils.isblank(cookie):
        return ""

    searchtype = "Code" if utils.isblank(searchtype) else searchtype
    sortedby = "indexed" if utils.isblank(sortedby) else sortedby
    query = build_query(("/api/v1/client/subscribe?token=",), regex=True) if utils.isblank(query) else query

    url = f"https://github.com/search?o=desc&p={page}&q={query}&s={sortedby}&type={searchtype}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Referer": "https://github.com",
        "User-Agent": utils.USER_AGENT,
        "Cookie": f"user_session={cookie}",
    }
    content = utils.http_get(url=url, headers=headers)
    if re.search(r"<h1>Sign in to GitHub</h1>", content, flags=re.I):
        logger.error("[GithubCrawl] session has expired, please provide a valid session and try again")
        return ""
    return content


def search_github_issues(page: int, cookie: str, query: str = "") -> list[str]:
    content = search_github(page=page, cookie=cookie, searchtype="Issues", sortedby="created", query=query)
    if utils.isblank(content):
        return []
    try:
        groups = re.findall(r'href="(/.*/.*/issues/\d+)">', content, flags=re.I)
        return [f"https://github.com{item}" for item in list(set(groups))]
    except Exception:
        return []


def search_github_issues_byapi(peer_page: int = 50, page: int = 1, query: str = "") -> list[str]:
    peer_page, page = min(max(peer_page, 1), 100), max(1, page)
    query = build_query(("/api/v1/client/subscribe?token=",)) if utils.isblank(query) else query
    url = f"https://api.github.com/search/issues?q={query}&sort=created&order=desc&per_page={peer_page}&page={page}"
    content = utils.http_get(url=url)
    if utils.isblank(content):
        return []
    try:
        items, links = json.loads(content).get("items", []), set()
        for item in items:
            link = item.get("html_url", "")
            if link:
                links.add(link)
        return list(links)
    except Exception:
        logger.error("[GithubIssuesCrawl] occur error when search issues from github")
        traceback.print_exc()
        return []


def search_github_code_byapi(
    token: str, peer_page: int = 50, page: int = 1, excludes: list[str] | None = None, query: str = ""
) -> list[str]:
    if utils.isblank(token):
        return []

    peer_page, page = min(max(peer_page, 1), 100), max(1, page)
    query = build_query(("/api/v1/client/subscribe?token=",)) if utils.isblank(query) else query
    url = f"https://api.github.com/search/code?q={query}&sort=indexed&order=desc&per_page={peer_page}&page={page}"
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    content = utils.http_get(url=url, headers=headers)
    if utils.isblank(content):
        return []
    try:
        items = json.loads(content).get("items", [])
        links = set()
        excludes = list(set(excludes or []))
        for item in items:
            if not item or not isinstance(item, dict):
                continue
            link = item.get("html_url", "")
            if not link:
                continue
            reponame = item.get("repository", {}).get("full_name", "") + "/"
            if not intercept(text=reponame, excludes=excludes):
                links.add(link)
        return list(links)
    except Exception:
        return []


def search_github_code(page: int, cookie: str, excludes: list[str] | None = None, query: str = "") -> list[str]:
    content = search_github(page=page, cookie=cookie, searchtype="Code", sortedby="indexed", query=query)
    if utils.isblank(content):
        return []
    try:
        groups = re.findall(r'href="(/[^\s"]+/blob/(?:[^"]+)?)#L\d+"', content, flags=re.I)
        uris = list(set(groups)) if groups else []
        links = set()
        excludes = list(set(excludes or []))
        for uri in uris:
            if not intercept(text=uri, excludes=excludes):
                links.add(f"https://github.com{uri}")
        return list(links)
    except Exception:
        return []


def _search_by_pattern(
    pattern: tuple[str, ...], config: GithubConfig, ctx: CrawlContext, token: str, cookie: str
) -> list[str]:
    """在给定模式下统一调度两种认证路径的搜索:代码 + Issues 双通道"""
    excludes = config.exclude_repos or []
    if utils.isblank(token):
        query = build_query(pattern, regex=True)
        params = [[item, cookie, excludes, query] for item in range(1, config.pages + 1)]
        results = utils.multi_thread_run(func=search_github_code, tasks=params, num_threads=ctx.num_threads)
        issues = search_github_issues(page=1, cookie=cookie, query=query)
    else:
        query = build_query(pattern)
        peer_page = 50
        params = [[token, peer_page, item, excludes, query] for item in paging(start=1, end=config.pages * 10, peer_page=peer_page)]
        results = utils.multi_thread_run(func=search_github_code_byapi, tasks=params, num_threads=ctx.num_threads)
        issues = search_github_issues_byapi(peer_page=5, page=1, query=query)

    links = list(set(itertools.chain.from_iterable(results)))
    return links + list(issues)


def crawl_github(config: GithubConfig, ctx: CrawlContext) -> ChannelResult:
    cookie = os.environ.get("GH_COOKIE", "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    if utils.isblank(cookie) and utils.isblank(token):
        logger.error("[GithubCrawl] cannot start crawl from github because cookie and token is missing")
        return ChannelResult()

    links, starttime = [], time.time()
    method = "search on the page" if utils.isblank(token) else "rest api"
    patterns = [tuple(p.split()) for p in (config.patterns or []) if utils.trim(p)] or DEFAULT_PATTERNS
    logger.info(f"[GithubCrawl] search patterns: {len(patterns)}, pages per pattern: {config.pages}")

    for pattern in patterns:
        links.extend(_search_by_pattern(pattern=pattern, config=config, ctx=ctx, token=token, cookie=cookie))

    page = PageChannel(
        include="",
        exclude=config.exclude,
        push_to=config.push_to,
        origin=Origin.GITHUB.name,
    )
    result = page.fetch_many(ctx, urls=list(dict.fromkeys(links)))
    logger.info(
        f"[GithubCrawl] finished crawl from Github through {method}, found {len(result.items)} subscriptions need check, cost: {time.time() - starttime:.2f}s"
    )
    return result


register_channel(GithubChannel())
