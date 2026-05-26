"""Georgian language helpers — date formatting and UI string constants."""

from __future__ import annotations

import datetime as dt

_DAYS = [
    "ორშაბათი", "სამშაბათი", "ოთხშაბათი",
    "ხუთშაბათი", "პარასკევი", "შაბათი", "კვირა",
]
_MONTHS = [
    "იანვარი", "თებერვალი", "მარტი", "აპრილი",
    "მაისი", "ივნისი", "ივლისი", "აგვისტო",
    "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
]
_MONTHS_SHORT = [
    "იანვ", "თებ", "მარ", "აპრ",
    "მაი", "ივნ", "ივლ", "აგვ",
    "სექ", "ოქტ", "ნოე", "დეკ",
]


def fmt_date(d: dt.date) -> str:
    """Return e.g. 'სამშაბათი, 22 აპრილი 2026'."""
    return f"{_DAYS[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]} {d.year}"


def fmt_short_date(d: dt.date) -> str:
    """Return e.g. '22 აპრ 2026'."""
    return f"{d.day} {_MONTHS_SHORT[d.month - 1]} {d.year}"


def fmt_month_year(d: dt.date) -> str:
    """Return e.g. 'აპრილი 2026'."""
    return f"{_MONTHS[d.month - 1]} {d.year}"


def picker_date(raw) -> dt.date:
    """Return the local calendar date from a Flet DatePicker value."""
    if isinstance(raw, dt.datetime):
        if raw.tzinfo is not None:
            return raw.astimezone().date()
        if raw.time() != dt.time.min:
            return raw.replace(tzinfo=dt.UTC).astimezone().date()
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    return dt.date.fromisoformat(str(raw)[:10])
