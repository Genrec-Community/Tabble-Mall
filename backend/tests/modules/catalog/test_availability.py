from datetime import datetime
from zoneinfo import ZoneInfo

from mallt.modules.catalog.availability import in_hours, store_accepting

IST = ZoneInfo("Asia/Kolkata")
# 2026-10-28 is a Wednesday (weekday 2).
WED_10 = datetime(2026, 10, 28, 10, 0, tzinfo=IST)
WED_23 = datetime(2026, 10, 28, 23, 0, tzinfo=IST)
WED_0130 = datetime(2026, 10, 28, 1, 30, tzinfo=IST)


def test_no_hours_means_always_open() -> None:
    assert in_hours([], WED_23, "open", "close")


def test_inside_and_outside_a_window() -> None:
    hours = [{"days": [2], "open": "09:00", "close": "22:00"}]
    assert in_hours(hours, WED_10, "open", "close")
    assert not in_hours(hours, WED_23, "open", "close")
    assert not in_hours([{"days": [3], "open": "09:00", "close": "22:00"}], WED_10, "open", "close")


def test_window_past_midnight_belongs_to_the_day_it_opened() -> None:
    # Open Tuesday 18:00 -> 02:00: Wednesday 01:30 is still open.
    hours = [{"days": [1], "open": "18:00", "close": "02:00"}]
    assert in_hours(hours, WED_0130, "open", "close")
    assert not in_hours(hours, WED_10, "open", "close")


def test_store_accepting_needs_open_unpaused_and_in_hours() -> None:
    hours = [{"days": [2], "open": "09:00", "close": "22:00"}]
    assert store_accepting(True, False, hours, "Asia/Kolkata", WED_10)
    assert not store_accepting(False, False, hours, "Asia/Kolkata", WED_10)
    assert not store_accepting(True, True, hours, "Asia/Kolkata", WED_10)
    assert not store_accepting(True, False, hours, "Asia/Kolkata", WED_23)
