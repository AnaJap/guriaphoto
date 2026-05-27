"""Single source of truth for time/date in the studio's timezone.

Georgia (Asia/Tbilisi) is **UTC+4 all year** — it observes no daylight saving —
so a fixed offset is correct and avoids depending on the host machine's clock
settings (which matters for the packaged Windows app, where ``time.tzset()`` is
not available).

Storage convention: timestamps are stored in **UTC** (the model defaults use
``datetime.now(UTC)``). Convert to local GMT+4 only at display time with
``to_local``. Use ``now()`` / ``today()`` for new local timestamps and the
business "today".
"""

from __future__ import annotations

import datetime as _dt

# Fixed +04:00 offset — Asia/Tbilisi, no DST.
GEO_TZ = _dt.timezone(_dt.timedelta(hours=4), name="GMT+4")


def now() -> _dt.datetime:
    """Current time as a timezone-aware datetime in GMT+4."""
    return _dt.datetime.now(GEO_TZ)


def today() -> _dt.date:
    """The current calendar date in GMT+4 (the studio's business day)."""
    return now().date()


def to_local(value: _dt.datetime | None) -> _dt.datetime | None:
    """Convert a stored timestamp to GMT+4 for display.

    Naive datetimes are assumed to be UTC (that's how they are stored). Returns
    ``None`` unchanged so callers can guard optional fields.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(GEO_TZ)
