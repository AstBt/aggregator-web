# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field

from config.models import NodeInput, StorageConfig, TaskParams
from push import PushTo


@dataclass
class SubItem:
    url: str
    origin: str
    task: TaskParams = field(default_factory=TaskParams)
    name: str = ""
    ready: bool = False
    persist_only: bool = False
    skip_cache: bool = False
    allow_nonstandard: bool = False
    errors: int = 0
    discovered: bool = False
    debut: bool = False


@dataclass
class ChannelResult:
    nodes: NodeInput = field(default_factory=NodeInput)
    items: list[SubItem] = field(default_factory=list)
    node_groups: list[str] = field(default_factory=list)

    def merge(self, other: ChannelResult | None) -> ChannelResult:
        if not other:
            return self
        subs = self.nodes.subscribe_list() + other.nodes.subscribe_list()
        self.nodes.subscribe = list(dict.fromkeys(subs))
        self.nodes.uris = list(dict.fromkeys(self.nodes.uris + other.nodes.uris))
        self.nodes.proxies.extend(other.nodes.proxies)
        self.items.extend(other.items)
        self.node_groups = list(dict.fromkeys(self.node_groups + other.node_groups))
        return self

    def add_subscribe(
        self,
        url: str,
        origin: str,
        task: TaskParams | None = None,
        name: str = "",
        ready: bool = False,
        persist_only: bool = False,
        skip_cache: bool = False,
        allow_nonstandard: bool = False,
        errors: int = 0,
        discovered: bool = False,
        debut: bool = False,
    ) -> None:
        url = (url or "").strip()
        if not url:
            return
        task = task or TaskParams()
        self.items.append(
            SubItem(
                url=url,
                origin=origin,
                task=task,
                name=name,
                ready=ready,
                persist_only=persist_only,
                skip_cache=skip_cache,
                allow_nonstandard=allow_nonstandard,
                errors=errors,
                discovered=discovered,
                debut=debut,
            )
        )
        current = self.nodes.subscribe_list()
        if url not in current:
            current.append(url)
        self.nodes.subscribe = current

@dataclass
class CrawlContext:
    mode: int
    include_nodes: bool
    max_fails: int
    exclude: str
    task: TaskParams
    storage: StorageConfig | None
    pushtool: PushTo | None
    num_threads: int = 50
    display: bool = True
    proxy: str = ""
