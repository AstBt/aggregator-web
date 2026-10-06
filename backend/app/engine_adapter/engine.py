# -*- coding: utf-8 -*-
"""真实引擎：复用 subscribe/ 现有模块完成 抓取→拉取→验活→转换（PRD §5 复用策略）。

Web 层不重写引擎：本类把 DB 配置合成为 ProcessConfig 语义的 CrawlConfig，
直接调用 crawl.engine.run / workflow.executewrapper / pipeline.check_alive_proxies /
subconverter 的既有实现。测试使用 HermeticEngine（runner.py）注入。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

SUBSCRIBE_DIR = Path(__file__).resolve().parents[3] / "subscribe"
PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(SUBSCRIBE_DIR) not in sys.path:
    sys.path.insert(0, str(SUBSCRIBE_DIR))

from engine_adapter.runner import CrawlOutcome, LooseNode, RunContext  # noqa: E402

try:
    from logger import logger  # noqa: E402
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger("engine")


_GROUP_PLACEHOLDER = "web"  # 无分组模型下供引擎筛选的占位分组名

_PROXY_ENV = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")


class proxy_scope:
    """本地代理作用域：爬取参数启用本地代理时，运行期间注入进程级代理 env，结束恢复。

    复用引擎 CLI 的 httpclient.configure_proxy 语义（探测代理可达后才注入，外部请求
    代理优先、传输失败自动回退直连，localhost 强制直连）。任务全局串行执行，进程级
    env 注入无并发冲突；节点验活不受影响（流量经 mihomo 直连节点，控制器为 localhost）。
    """

    def __init__(self, session) -> None:
        self._session = session
        self._snapshot: dict[str, str | None] = {}
        self.applied = ""

    def __enter__(self) -> "proxy_scope":
        from models import Setting

        setting = self._session.get(Setting, "crawl")
        proxy = (dict(setting.value) if setting else {}).get("proxy") or {}
        self._snapshot = {key: os.environ.get(key) for key in _PROXY_ENV}
        if proxy.get("enable") and proxy.get("address"):
            import httpclient

            self.applied = httpclient.configure_proxy(
                True, proxy["address"], proxy.get("test_url") or "https://api.github.com/zen"
            )
        return self

    def __exit__(self, *exc) -> None:
        for key, value in self._snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RealEngine:
    """生产引擎。"""

    # ---------- 抓取 ----------
    def crawl(self, ctx: RunContext) -> "CrawlOutcome":
        """按爬取源逐渠道执行：订阅（带来源）+ 散节点（按源归属）。

        不使用 crawl.engine.run 的合并入口：那会把全部渠道的散节点合并为
        单个 crawled-nodes 站点，丢失来源归属；逐源调用可获得「哪个源产出
        哪些散节点」，供结果页按爬取源名称（TG 为频道名）展示。
        """
        from crawl.base import CHANNELS
        from crawl.models import CrawlContext

        crawl_ctx = CrawlContext(
            mode=1,
            include_nodes=True,
            max_fails=5,
            exclude="",
            task=None,
            storage=None,
            pushtool=None,
            num_threads=int(ctx.params.get("num_threads", 32)),
            display=False,
            proxy="",
        )
        found: list[tuple[str, str]] = []
        loose: list[LooseNode] = []
        for source_name, channel_key, section, credentials in _build_sections(ctx):
            channel = CHANNELS.get(channel_key)
            if channel is None:
                continue
            try:
                with _env_scope(credentials):
                    result = channel.crawl(section, crawl_ctx)
            except Exception as exc:  # noqa: BLE001 — 单源失败不拖垮整轮
                logger.warning(f"[WebEngine] crawl source failed, name={source_name}, error={exc}")
                continue
            for item in result.items:
                found.append((item.url, item.origin or "TEMPORARY"))
            for uri in result.nodes.uris:
                loose.append(LooseNode(source=source_name, uri=uri))
            for proxy in result.nodes.proxies:
                loose.append(LooseNode(source=source_name, proxy=dict(proxy)))

        reachable = _validate_subscriptions([url for url, _ in found], ctx)
        return CrawlOutcome(
            subscriptions=[(url, origin, reachable.get(url, False)) for url, origin in found],
            loose=loose,
        )

    # ---------- 拉取节点 ----------
    def fetch(self, ctx: RunContext, subscriptions: list[str], loose: list["LooseNode"]) -> list[dict]:
        """两路拉取：订阅 URL 解析（kind=sub）+ 散节点（kind=crawl，按源打标）。"""
        import executable
        import workflow
        from config.models import NodeInput

        _, subconverter_bin = executable.which_bin()
        tasks: list[tuple[object, dict]] = []
        for index, url in enumerate(subscriptions):
            task = workflow.TaskConfig(
                name=f"sub-{index}",
                bin_name=subconverter_bin,
                taskid=index + 1,
                nodes=NodeInput(subscribe=url),
                index=-1,
                retry=2,
                max_rate=3.0,
            )
            tasks.append((task, {"_kind": "sub", "_source_sub": url}))
        by_source: dict[str, list[str]] = {}
        for item in loose:
            if item.uri:
                by_source.setdefault(item.source, []).append(item.uri)
        for source, uris in by_source.items():
            task = workflow.TaskConfig(
                name=f"crawl-{source}",
                bin_name=subconverter_bin,
                taskid=len(tasks) + 1,
                nodes=NodeInput(uris=list(dict.fromkeys(uris))),
                index=-1,
                retry=2,
                max_rate=3.0,
            )
            tasks.append((task, {"_kind": "crawl", "_source": source}))

        proxies: list[dict] = [{**item.proxy, "_kind": "crawl", "_source": item.source} for item in loose if item.proxy]
        for task, marker in tasks:
            if ctx.cancelled:
                break
            try:
                _taskid, items = workflow.executewrapper(task)
            except Exception as exc:  # noqa: BLE001 — 单个订阅失败不拖垮整轮
                logger.warning(f"[WebEngine] fetch failed, name={task.name}, error={exc}")
                continue
            for item in items:
                merged = dict(item)
                merged.update(marker)
                proxies.append(merged)
        return proxies

    # ---------- 验活 ----------
    def check(self, ctx: RunContext, proxies: list[dict]) -> list[dict]:
        import clash
        import executable
        import pipeline

        clash_bin, _ = executable.which_bin()
        alive = pipeline.check_alive_proxies(
            proxies=proxies,
            clash_bin=clash_bin,
            workspace=str(PROJECT_DIR / "clash"),
            filename="config.yaml",
            timeout=int(ctx.params.get("timeout", 5000)),
            test_url=str(ctx.params.get("test_url", "https://www.google.com/generate_204")),
            delay=int(ctx.params.get("max_delay", 5000)),
            num_threads=int(ctx.params.get("num_threads", 32)),
            display=False,
            skip=False,
            group="web",
        )
        return alive

    # ---------- 转换 ----------
    def convert(self, ctx: RunContext, alive: list[dict]) -> list[dict]:
        """转换存活节点为 clash / v2ray / singbox。

        subconverter 进程以其所在目录为工作目录，generate.ini 与源文件必须落在
        subconverter/ 下；转换成功后把产物移到临时目录，避免污染仓库并供发布器读取。
        """
        import subconverter

        import executable

        _, subconverter_bin = executable.which_bin()
        workdir = os.path.join(PROJECT_DIR, "subconverter")
        directory = tempfile.mkdtemp(prefix="agg-convert-")
        data = {"proxies": clash_filtered(alive)}
        with open(os.path.join(workdir, "config.yaml"), "w", encoding="utf8") as f:
            yaml.add_representer(_quoted(), _quoted_repr)
            yaml.dump(data, f, allow_unicode=True)

        specs = []
        try:
            for target in ("clash", "v2ray", "singbox"):
                dest = subconverter.get_filename(target=target)
                ok = subconverter.generate_conf(
                    filepath=os.path.join(workdir, "generate.ini"),
                    name=f"convert_{target}",
                    source="config.yaml",
                    dest=dest,
                    target=target,
                    emoji=True,
                    list_only=True,
                )
                if not ok or not subconverter.convert(binname=subconverter_bin, artifact=f"convert_{target}"):
                    logger.warning(f"[WebEngine] convert failed, target={target}")
                    continue
                produced = os.path.join(workdir, dest)
                if not os.path.isfile(produced):
                    continue
                if os.path.getsize(produced) <= 0:
                    logger.warning(f"[WebEngine] empty artifact skipped, target={target}")
                    os.remove(produced)
                    continue
                moved = os.path.join(directory, dest)
                shutil.move(produced, moved)
                specs.append({"target": target, "path": moved, "size": os.path.getsize(moved)})
        finally:
            for name in ("config.yaml", "generate.ini"):
                stale = os.path.join(workdir, name)
                if os.path.isfile(stale):
                    try:
                        os.remove(stale)
                    except OSError:
                        pass
        return specs


def clash_filtered(proxies: list[dict]) -> list[dict]:
    import clash

    return clash.filter_proxies([dict(p) for p in proxies])["proxies"]


def _quoted():
    import clash

    return clash.QuotedStr


def _quoted_repr(dumper, data):
    import clash

    return clash.quoted_scalar(dumper, data)


def _build_sections(ctx: RunContext) -> list[tuple[str, str, object, dict]]:
    """DB 源 → 每个源的 (源名称, 渠道键, 渠道配置对象, 凭证字典)。

    凭证（github token/cookie、gist gh_cookie/token）由调用方注入环境变量；
    gist 的 mode 决定读取哪个凭证（search 需要 cookie+token，timeline 用 token）。
    """
    import db
    from config.models import (
        GithubConfig,
        GoogleConfig,
        GistConfig,
        PageJob,
        RepoConfig,
        ScriptJob,
        TelegramChannelConfig,
        TelegramConfig,
        TaskParams,
        YandexConfig,
    )
    from models import CrawlSource

    session = db.SessionLocal()
    try:
        sources = session.query(CrawlSource).filter_by(enable=True).all()
        if ctx.source_ids:
            wanted = {int(x) for x in ctx.source_ids}
            sources = [s for s in sources if s.id in wanted]
    finally:
        session.close()

    sections: list[tuple[str, str, object, dict]] = []
    for source in sources:
        cfg = dict(source.config or {})
        if source.type == "telegram":
            section = TelegramConfig(
                enable=True,
                pages=int(cfg.get("pages", 5)),
                exclude="",
                channels={
                    source.name: TelegramChannelConfig(
                        include=cfg.get("include", ""),
                        exclude=cfg.get("exclude", ""),
                        push_to=[_GROUP_PLACEHOLDER],
                        task=TaskParams(include="", exclude="", rename=cfg.get("rename", "")),
                    )
                },
            )
            sections.append((source.name, "telegram", section, {}))
        elif source.type == "github":
            section = GithubConfig(
                enable=True,
                pages=int(cfg.get("pages", 2)),
                push_to=[_GROUP_PLACEHOLDER],
                exclude=cfg.get("exclude", ""),
                exclude_repos=list(cfg.get("exclude_repos", [])),
                patterns=list(cfg.get("patterns", [])),
            )
            creds = {}
            if cfg.get("token"):
                creds["GH_TOKEN"] = cfg["token"]
            if cfg.get("cookie"):
                creds["GH_COOKIE"] = cfg["cookie"]
            sections.append((source.name, "github", section, creds))
        elif source.type == "gist":
            mode = cfg.get("mode", "timeline")
            section = GistConfig(
                enable=True,
                push_to=[_GROUP_PLACEHOLDER],
                include=cfg.get("include", ""),
                exclude=cfg.get("exclude", ""),
                exclude_owners=list(cfg.get("exclude_owners", [])),
                max_gists=int(cfg.get("max_gists", 100)),
                max_filesize=int(cfg.get("max_filesize", 65536)),
                patterns=list(cfg.get("patterns", [])),
                pages=int(cfg.get("pages", 2)),
            )
            creds = {}
            if mode == "search" and cfg.get("gh_cookie"):
                # 渠道以 GH_COOKIE 是否存在切换 search/timeline
                creds["GH_COOKIE"] = cfg["gh_cookie"]
            if cfg.get("token"):
                creds.setdefault("GH_TOKEN", cfg["token"])
            sections.append((source.name, "gist", section, creds))
        elif source.type == "google":
            section = GoogleConfig(
                enable=True,
                push_to=[_GROUP_PLACEHOLDER],
                exclude=cfg.get("exclude", ""),
                limit=int(cfg.get("limit", 100)),
                days=int(cfg.get("days", 7)),
                exclude_sites=list(cfg.get("exclude_sites", [])),
            )
            sections.append((source.name, "google", section, {}))
        elif source.type == "yandex":
            section = YandexConfig(
                enable=True,
                push_to=[_GROUP_PLACEHOLDER],
                exclude=cfg.get("exclude", ""),
                days=int(cfg.get("days", 3)),
                pages=int(cfg.get("pages", 5)),
                exclude_sites=list(cfg.get("exclude_sites", [])),
            )
            sections.append((source.name, "yandex", section, {}))
        elif source.type == "page":
            # page 渠道接收 list[PageJob]（与引擎 run() 一致）
            section = [
                PageJob(
                    url=list(cfg.get("url", [])),
                    enable=True,
                    paged=bool(cfg.get("paged", False)),
                    placeholder=cfg.get("placeholder", "{page}"),
                    start=int(cfg.get("start", 1)),
                    end=int(cfg.get("end", 5)),
                    headers=cfg.get("headers") or None,
                    push_to=[_GROUP_PLACEHOLDER],
                )
            ]
            sections.append((source.name, "pages", section, {}))
        elif source.type == "repo":
            # repository 渠道接收 list[RepoConfig]
            section = [
                RepoConfig(
                    enable=True,
                    username=cfg.get("username", ""),
                    repo=cfg.get("repo", ""),
                    commits=int(cfg.get("commits", 3)),
                    push_to=[_GROUP_PLACEHOLDER],
                    exclude=cfg.get("exclude", ""),
                )
            ]
            sections.append((source.name, "repositories", section, {}))
        elif source.type == "script":
            if not cfg.get("plugin"):
                continue
            options = cfg.get("options") or {}
            # script 渠道接收 list[ScriptJob]
            section = [
                ScriptJob(
                    plugin=cfg["plugin"],
                    enable=True,
                    persist=cfg.get("persist"),
                    options=dict(options) if isinstance(options, dict) else {},
                )
            ]
            sections.append((source.name, "scripts", section, {}))
    return sections


def _validate_subscriptions(urls: list[str], ctx: RunContext) -> dict[str, bool]:
    """并发探测订阅可达性（复用引擎的 check_status）。"""
    from functools import partial

    import utils
    from crawl.helpers import check_status

    if not urls:
        return {}
    masks = utils.multi_thread_run(
        func=partial(check_status, proxy=""),
        tasks=[[url, 2, 5, 12, 72] for url in urls],
        num_threads=int(ctx.params.get("num_threads", 32)),
        show_progress=False,
    )
    reachable: dict[str, bool] = {}
    for url, mask in zip(urls, masks):
        ok = False
        if isinstance(mask, tuple) and len(mask) >= 1:
            ok = bool(mask[0])
        reachable[url] = ok
    return reachable
class _env_scope:
    """临时注入环境变量，退出时还原（线程内串行使用）。"""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self._backup: dict[str, str | None] = {}

    def __enter__(self) -> "_env_scope":
        import os

        for key, value in self._values.items():
            self._backup[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *_) -> None:
        import os

        for key, old in self._backup.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
