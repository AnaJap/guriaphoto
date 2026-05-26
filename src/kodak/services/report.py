"""Report service — aggregate data for period reports."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from kodak.models.cash import CashWithdrawal
from kodak.services.history import (
    RangeSummary,
    list_range_transactions,
    summarize_range,
)


@dataclass
class DayStat:
    date: dt.date
    txn_count: int
    revenue: Decimal
    withdrawn: Decimal

    @property
    def net(self) -> Decimal:
        return self.revenue - self.withdrawn


@dataclass
class ReportData:
    start: dt.date
    end: dt.date
    summary: RangeSummary
    total_withdrawn: Decimal
    net_cash: Decimal
    days: list[DayStat]  # newest first, only dates with activity


def build_report(session: Session, start: dt.date, end: dt.date) -> ReportData:
    details = list_range_transactions(session, start, end)
    summary = summarize_range(details)

    withdrawals = list(
        session.exec(
            select(CashWithdrawal)
            .where(CashWithdrawal.date >= start)
            .where(CashWithdrawal.date <= end)
        ).all()
    )
    total_withdrawn = sum(w.amount for w in withdrawals) or Decimal("0")
    net_cash = summary.total_revenue - total_withdrawn

    # per-day aggregation
    day_count:    dict[dt.date, int]     = defaultdict(int)
    day_revenue:  dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    day_withdrawn: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))

    for d in details:
        day_count[d.txn.date]   += 1
        day_revenue[d.txn.date] += d.total
    for w in withdrawals:
        day_withdrawn[w.date]   += w.amount

    all_dates = set(day_count) | set(day_withdrawn)
    days = sorted(
        [
            DayStat(
                date=date,
                txn_count=day_count[date],
                revenue=day_revenue[date],
                withdrawn=day_withdrawn[date],
            )
            for date in all_dates
        ],
        key=lambda d: d.date,
        reverse=True,
    )

    return ReportData(
        start=start,
        end=end,
        summary=summary,
        total_withdrawn=total_withdrawn,
        net_cash=net_cash,
        days=days,
    )


def last_day_of_month(d: dt.date) -> dt.date:
    """Return the last calendar day of d's month."""
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - dt.timedelta(days=1)
