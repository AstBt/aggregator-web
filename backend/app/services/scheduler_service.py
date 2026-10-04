# -*- coding: utf-8 -*-
"""定时构建器：图形化间隔 → cron（界面对用户不可见表达式，FR-4.8）。"""

from __future__ import annotations

import re

KINDS = ("minute", "hour", "day", "week", "daily", "weekly")
_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def to_cron(kind: str, *, n: int = 1, time: str = "00:00", weekdays: list[int] | None = None) -> str:
    """六种图形化间隔 → 标准 5 段 cron（本地时区）。"""
    if kind not in KINDS:
        raise ValueError(f"不支持的间隔类型: {kind}")
    hour, minute = _split_time(time)
    if kind == "minute":
        n = max(1, min(59, n))
        return f"*/{n} * * * *"
    if kind == "hour":
        n = max(1, min(23, n))
        return f"{minute} */{n} * * *"
    if kind == "day":
        n = max(1, min(30, n))
        return f"{minute} {hour} */{n} * *"
    if kind == "week":
        n = max(1, min(4, n))
        days = _weekdays(weekdays)
        return f"{minute} {hour} * * {days}"
    if kind == "daily":
        return f"{minute} {hour} * * *"
    # weekly
    days = _weekdays(weekdays)
    return f"{minute} {hour} * * {days}"


def describe(kind: str, *, n: int = 1, time: str = "00:00", weekdays: list[int] | None = None) -> str:
    if kind == "minute":
        return f"每 {max(1, n)} 分钟"
    if kind == "hour":
        return f"每 {max(1, n)} 小时"
    if kind == "day":
        return f"每 {max(1, n)} 天的 {time}"
    if kind == "week":
        days = "、".join(_WEEKDAY_LABELS[d - 1] for d in sorted(weekdays or [1]))
        return f"每 {max(1, n)} 周的{days}"
    if kind == "daily":
        return f"每天 {time}"
    days = "、".join(_WEEKDAY_LABELS[d - 1] for d in sorted(weekdays or [1]))
    return f"每周{days}的 {time}"


def _split_time(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value or "")
    if not match:
        raise ValueError("时间格式须为 HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间超出范围")
    return hour, minute


def _weekdays(days: list[int] | None) -> str:
    values = sorted({d for d in (days or [1]) if 1 <= d <= 7})
    if not values:
        values = [1]
    # ISO-8601(周一=1) → cron(周日=0)
    return ",".join(str(0 if d == 7 else d) for d in values)
