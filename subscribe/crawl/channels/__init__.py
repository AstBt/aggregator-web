# -*- coding: utf-8 -*-

from importlib import import_module

from crawl.base import CHANNELS

for _name in (
    "gist",
    "github",
    "google",
    "page",
    "repository",
    "script",
    "telegram",
    "yandex",
):
    import_module(f"{__name__}.{_name}")

__all__ = ["CHANNELS"]
