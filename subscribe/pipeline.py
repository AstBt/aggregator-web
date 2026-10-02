# -*- coding: utf-8 -*-

import os
import random
import subprocess
import time

import utils
import workflow
import yaml
from airport import AirPort
from config.models import GroupConfig, NodeInput, SiteConfig
from logger import logger
from origin import Origin
from workflow import TaskConfig, exists

import clash
import subconverter


def assign_sites(
    sites: list[SiteConfig],
    groups: dict[str, GroupConfig],
    retry: int,
    bin_name: str,
    allow_gmail_alias: bool = False,
    special_protocols: bool | None = None,
) -> tuple[list[TaskConfig], dict[str, list[int]]]:
    tasks, grouped = [], {}
    retry, globalid = max(1, retry), 0
    if special_protocols is None:
        special_protocols = AirPort.enable_special_protocols()

    for site in sites or []:
        if not isinstance(site, SiteConfig) or not site.enable:
            continue
        name = utils.trim(site.name).lower()
        domain = utils.trim(site.domain).lower()
        subscribe = site.nodes.subscribe_list()
        if len(subscribe) >= 2:
            subscribe = list(dict.fromkeys(subscribe))

        count = min(max(1, int(site.count)), 10)
        if subscribe:
            count = len(subscribe)
        if site.renew and site.renew.accounts:
            count = len(site.renew.accounts)

        source = site.origin
        if not source:
            source = Origin.TEMPORARY.name if not domain else Origin.OWNED.name
        site.origin = source
        if source != Origin.TEMPORARY.name:
            site.errors = max(site.errors, 0) + 1
        if name:
            site.name = name.rsplit("-", maxsplit=1)[0]

        if not name or (not domain and site.nodes.empty()) or count <= 0:
            continue

        if site.nodes.uris or site.nodes.proxies:
            globalid += 1
            task = TaskConfig(
                name=name,
                taskid=globalid,
                domain=domain,
                nodes=NodeInput(
                    subscribe=list(subscribe),
                    uris=list(site.nodes.uris),
                    proxies=list(site.nodes.proxies),
                ),
                index=-1,
                retry=retry,
                max_rate=site.max_rate,
                bin_name=bin_name,
                renew=(
                    site.renew.jobs(coupon=site.coupon, api_prefix=site.api_prefix)[0]
                    if site.renew and site.renew.accounts
                    else None
                ),
                rename=site.rename,
                exclude=site.exclude,
                include=site.include,
                check_alive=site.check_alive,
                coupon=site.coupon,
                require_tls=site.require_tls,
                ignore_default_exclude=site.ignore_default_exclude,
                allow_gmail_alias=allow_gmail_alias,
                skip_captcha=site.skip_captcha,
                special_protocols=special_protocols,
                invite_code=site.invite_code,
                api_prefix=site.api_prefix,
            )
            if not exists(tasks=tasks, task=task):
                tasks.append(task)
                for push_name in site.push_to:
                    grouped.setdefault(push_name, []).append(globalid)
            continue

        for index in range(count):
            globalid += 1
            sub = subscribe[index] if index < len(subscribe) else ""
            renew = None
            if site.renew:
                jobs = site.renew.jobs(coupon=site.coupon, api_prefix=site.api_prefix)
                if index < len(jobs):
                    renew = jobs[index]
            task = TaskConfig(
                name=name,
                taskid=globalid,
                domain=domain,
                nodes=NodeInput(subscribe=sub),
                index=-1 if count == 1 else index + 1,
                retry=retry,
                max_rate=site.max_rate,
                bin_name=bin_name,
                renew=renew,
                rename=site.rename,
                exclude=site.exclude,
                include=site.include,
                check_alive=site.check_alive,
                coupon=site.coupon,
                require_tls=site.require_tls,
                ignore_default_exclude=site.ignore_default_exclude,
                allow_gmail_alias=allow_gmail_alias,
                skip_captcha=site.skip_captcha,
                special_protocols=special_protocols,
                invite_code=site.invite_code,
                api_prefix=site.api_prefix,
            )
            if exists(tasks=tasks, task=task):
                continue
            tasks.append(task)
            for push_name in site.push_to:
                if push_name not in groups:
                    logger.error(f"cannot found push config, name=[{push_name}]\tsite=[{name}]")
                    continue
                grouped.setdefault(push_name, []).append(globalid)

    return tasks, grouped




def check_alive_proxies(
    proxies: list[dict[str, object]],
    clash_bin: str,
    workspace: str,
    filename: str = "config.yaml",
    timeout: int = 5000,
    test_url: str = "https://www.google.com/generate_204",
    delay: int = 5000,
    num_threads: int = 64,
    display: bool = True,
    skip: bool = False,
    group: str = "",
) -> list[dict[str, object]]:
    if not proxies:
        return []

    proxies = clash.generate_config(workspace, proxies, filename)
    if skip:
        return proxies

    checks, nochecks = workflow.liveness_fillter(proxies=proxies)
    if not checks:
        return nochecks

    binpath = os.path.join(workspace, clash_bin)
    utils.chmod(binpath)
    logger.info(f"startup clash now, workspace: {workspace}, config: {filename}")
    process = subprocess.Popen([binpath, "-d", workspace, "-f", os.path.join(workspace, filename)])
    logger.info(f"clash start success, begin check proxies, group: {group}\tcount: {len(checks)}")
    time.sleep(random.randint(5, 8))
    params = [
        [item, clash.EXTERNAL_CONTROLLER, timeout, test_url, delay, False] for item in checks if isinstance(item, dict)
    ]
    masks = utils.multi_thread_run(func=clash.check, tasks=params, num_threads=num_threads, show_progress=display)
    try:
        process.terminate()
    except Exception:
        logger.error(f"terminate clash process error, group: {group}")

    availables = [checks[i] for i in range(len(checks)) if masks[i]]
    nochecks.extend(availables)
    logger.info(
        f"proxies check finished, total: {len(checks)}, alive: {len(availables)}, dead: {len(checks) - len(availables)}"
    )
    return nochecks


