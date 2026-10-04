# -*- coding: utf-8 -*-
"""真实引擎：复用 subscribe/ 现有模块完成 抓取→拉取→验活→转换（PRD §5 复用策略）。

Web 层不重写引擎：本类把 DB 配置合成为 ProcessConfig 语义的 CrawlConfig，
直接调用 crawl.engine.run / workflow.executewrapper / pipeline.check_alive_proxies /
subconverter 的既有实现。测试使用 HermeticEngine（runner.py）注入。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

SUBSCRIBE_DIR = Path(__file__).resolve().parents[3] / "subscribe"
PROJECT_DIR = Path(__file__).resolve().parents[3]
if str(SUBSCRIBE_DIR) not in sys.path:
    sys.path.insert(0, str(SUBSCRIBE_DIR))

from engine_adapter.runner import RunContext  # noqa: E402


class RealEngine:
    """生产引擎。"""

    # ---------- 抓取 ----------
    def crawl(self, ctx: RunContext) -> list[tuple[str, str, bool]]:
        from crawl.engine import run as crawl_run
        from config.models import CrawlConfig, Node as ConfNode, StorageConfig

        config = CrawlConfig.parse(ConfNode(_crawl_config_dict(ctx)), StorageConfig())
        if not config.enable:
            return []
        sites = crawl_run(config, storage=None, num_threads=ctx.params.get("num_threads", 32), display=False, mode=0)
        out: list[tuple[str, str, bool]] = []
        for site in sites:
            for url in site.nodes.subscribe_list():
                out.append((url, site.origin or "TEMPORARY", True))
        return out

    # ---------- 拉取节点 ----------
    def fetch(self, ctx: RunContext, subscriptions: list[str]) -> list[dict]:
        import utils
        import workflow

        tasks = []
        for index, url in enumerate(subscriptions):
            from config.models import NodeInput

            tasks.append(
                workflow.TaskConfig(
                    name=f"sub-{index}",
                    bin_name="",
                    taskid=index + 1,
                    nodes=NodeInput(subscribe=url),
                    index=-1,
                    retry=2,
                    max_rate=3.0,
                )
            )
        if not tasks:
            return []
        proxies: list[dict] = []
        for task in tasks:
            if ctx.cancelled:
                break
            _taskid, items = workflow.executewrapper(task)
            proxies.extend(items)
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
        import subconverter

        _, subconverter_bin = executable.which_bin()
        directory = tempfile.mkdtemp(prefix="agg-convert-")
        data = {"proxies": clash_filtered(alive)}
        source = os.path.join(directory, "config.yaml")
        with open(source, "w", encoding="utf8") as f:
            yaml.add_representer(_quoted(), _quoted_repr)
            yaml.dump(data, f, allow_unicode=True)
        specs = []
        for target in ("clash", "v2ray", "singbox"):
            dest = subconverter.get_filename(target=target)
            destination = os.path.join(directory, dest)
            generate_conf = os.path.join(directory, "generate.ini")
            ok = subconverter.generate_conf(
                filepath=generate_conf, name=f"convert_{target}", source="config.yaml", dest=dest,
                target=target, emoji=True, list_only=True,
            )
            if not ok or not subconverter.convert(binname=subconverter_bin, artifact=f"convert_{target}"):
                continue
            path = os.path.join(PROJECT_DIR, "subconverter", dest)
            if os.path.isfile(path):
                specs.append({"target": target, "path": path, "size": os.path.getsize(path)})
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


def _crawl_config_dict(ctx: RunContext) -> dict:
    """DB 源 + 参数 → CrawlConfig 可解析字典（仅源信息，不含 push_to 等分组残留）。"""
    import db
    from models import CrawlSource, Setting

    session = db.SessionLocal()
    try:
        sources = session.query(CrawlSource).filter_by(enable=True).all()
        crawl_setting = (session.get(Setting, "crawl").value if session.get(Setting, "crawl") else {}) or {}
        by_type: dict[str, list] = {}
        for source in sources:
            by_type.setdefault(source.type, []).append(source)
        config: dict = {
            "enable": True,
            "exclude": crawl_setting.get("exclude", ""),
            "max_fails": int(crawl_setting.get("max_fails", 5)),
            "include_nodes": bool(crawl_setting.get("include_nodes", True)),
            "task": {"include": crawl_setting.get("include", ""), "exclude": crawl_setting.get("exclude_task", "")},
        }
        telegram = by_type.get("telegram") or []
        if telegram:
            config["telegram"] = {"enable": True, "channels": {s.name: s.config for s in telegram}}
        for key in ("google", "yandex", "github", "gist"):
            rows = by_type.get(key) or []
            if rows:
                config[key] = {"enable": True, **rows[0].config}
        pages = by_type.get("page") or []
        if pages:
            config["pages"] = [{**s.config, "enable": True} for s in pages]
        repos = by_type.get("repo") or []
        if repos:
            config["repositories"] = [s.config for s in repos]
        scripts = by_type.get("script") or []
        if scripts:
            config["scripts"] = [{**s.config, "enable": True} for s in scripts]
        project_setting = (session.get(Setting, "proxy").value if session.get(Setting, "proxy") else {}) or {}
        config["proxy"] = dict(project_setting)
        return config
    finally:
        session.close()
