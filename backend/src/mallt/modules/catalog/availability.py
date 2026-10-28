"""Pure opening-hours / availability-window logic (local time of the store)."""

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo


def _t(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def in_hours(windows: list[dict[str, Any]], now: datetime, start_key: str, end_key: str) -> bool:
    """True when ``now`` (already in local time) falls in any window; no windows = always.

    A window whose end is not after its start runs past midnight and belongs to the day it
    opened on, so Tuesday 18:00-02:00 is still open at Wednesday 01:30."""
    if not windows:
        return True
    clock, weekday = now.time(), now.weekday()
    for w in windows:
        start, end, days = _t(w[start_key]), _t(w[end_key]), w["days"]
        if start < end:
            if weekday in days and start <= clock < end:
                return True
        else:
            if weekday in days and clock >= start:
                return True
            if (weekday - 1) % 7 in days and clock < end:
                return True
    return False


def store_accepting(
    is_open: bool,
    is_paused: bool,
    hours: list[dict[str, Any]],
    timezone: str,
    now: datetime,
) -> bool:
    if not is_open or is_paused:
        return False
    return in_hours(hours, now.astimezone(ZoneInfo(timezone)), "open", "close")
