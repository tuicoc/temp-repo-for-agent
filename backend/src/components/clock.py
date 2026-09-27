"""The virtual clock. ``docs/design.md`` Appendix A.

Business logic reads ``now`` from the state, never the system clock: the
evaluation runner sets it to the scenario's day, the API to the business day
the Admin page chose (by default the organisers' "today", 2026-10-15, the
day their catalogue, promotions and stock are written for). The time of day
of a call is fixed at 10:00, Vietnam time. Tools take the day as ``on``,
``YYYY-MM-DD``. Latency is measured on the real, monotonic clock, never this
one.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

VIETNAM = timezone(timedelta(hours=7))

#: Appendix A: the time of day every call is placed at, recorded in the manifest.
CALL_TIME = time(10, 0)

#: The organisers' reference date, the default business day.
REFERENCE_DAY = "2026-10-15"


def at(day: str | date) -> datetime:
    """10:00 in Vietnam on *day*."""
    if isinstance(day, str):
        day = date.fromisoformat(day[:10])
    return datetime.combine(day, CALL_TIME, tzinfo=VIETNAM)


def on(now: datetime) -> str:
    """The ``on`` argument of a tool: the day of *now* in Vietnam."""
    return now.astimezone(VIETNAM).date().isoformat()


def day_label(value: str | date | datetime) -> str:
    """``15/10/2026``, as the advisor says a date."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        value = value.astimezone(VIETNAM).date()
    return value.strftime("%d/%m/%Y")
