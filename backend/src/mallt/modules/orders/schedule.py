"""Schedule ahead: the customer picks when to collect. Pure, so it is easy to test.

A pickup time must leave the slowest store in the cart enough time to cook, fall inside every
store's opening hours, and be within ``MAX_AHEAD`` (stores plan a day, not a week).
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from mallt.modules.catalog.service import OrderableStore

SLOT = timedelta(minutes=15)
MAX_AHEAD = timedelta(hours=12)
MAX_SLOTS = 48
# A little slack: the customer picked the slot a minute ago on a page that was then current.
SLACK = timedelta(minutes=3)


def earliest(now: datetime, prep_minutes: int) -> datetime:
    return now + timedelta(minutes=prep_minutes)


def _ceil(t: datetime) -> datetime:
    base = t.replace(second=0, microsecond=0)
    over = base.minute % 15
    if over or t != base:
        base += timedelta(minutes=15 - over)
    return base


def slots(now: datetime, prep_minutes: int, stores: Iterable[OrderableStore]) -> list[datetime]:
    """15-minute pickup slots every store is open for, starting after the food can be ready."""
    stores = list(stores)
    first = _ceil(earliest(now, prep_minutes) + timedelta(minutes=5))
    out: list[datetime] = []
    t = first
    while t <= now + MAX_AHEAD and len(out) < MAX_SLOTS:
        if all(s.open_at(t) for s in stores):
            out.append(t)
        t += SLOT
    return out


def problem(
    pickup_at: datetime, now: datetime, prep_minutes: int, stores: Iterable[OrderableStore]
) -> str | None:
    """Why ``pickup_at`` can't be used, in words for the customer, or None if it can."""
    if pickup_at.tzinfo is None:
        return "Send the pickup time with its time zone."
    if pickup_at < earliest(now, prep_minutes) - SLACK:
        return f"Your food needs about {prep_minutes} minutes. Pick a later time."
    if pickup_at > now + MAX_AHEAD:
        return "You can schedule up to 12 hours ahead."
    closed = [s.name for s in stores if not s.open_at(pickup_at)]
    if closed:
        return f"{', '.join(sorted(closed))} will be closed then. Pick another time."
    return None
