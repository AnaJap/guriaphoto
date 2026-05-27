"""Report service — aggregate data for period reports."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from kodak import clock
from kodak.models.cash import CashWithdrawal
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus
from kodak.models.transaction import Transaction
from kodak.services.history import (
    RangeSummary,
    list_range_transactions,
    summarize_range,
)


@dataclass
class DayStat:
    date: dt.date
    txn_count: int
    sales_total: Decimal
    sales_received: Decimal
    new_credit_count: int
    credit_repaid: Decimal
    credit_repaid_count: int
    withdrawn: Decimal
    opening_balance: Decimal
    closing_balance: Decimal
    forgiven_amount: Decimal = Decimal("0")
    forgiven_count: int = 0

    @property
    def income(self) -> Decimal:
        return self.sales_received + self.credit_repaid

    @property
    def net_change(self) -> Decimal:
        return self.income - self.withdrawn


@dataclass
class ReportData:
    start: dt.date
    end: dt.date
    summary: RangeSummary
    opening_balance: Decimal
    sales_received: Decimal
    credit_repaid: Decimal
    credit_repaid_count: int
    total_withdrawn: Decimal
    net_change: Decimal
    closing_balance: Decimal
    active_credit_count: int
    active_credit_amount: Decimal
    forgiven_amount: Decimal
    forgiven_count: int
    days: list[DayStat]  # newest first, only dates with activity


def build_report(session: Session, start: dt.date, end: dt.date) -> ReportData:
    details = list_range_transactions(session, start, end)
    summary = summarize_range(details, session=session, start=start, end=end)

    withdrawals = list(
        session.exec(
            select(CashWithdrawal)
            .where(CashWithdrawal.date >= start)
            .where(CashWithdrawal.date <= end)
        ).all()
    )
    total_withdrawn = sum(w.amount for w in withdrawals) or Decimal("0")
    sales_received = summary.received_from_sales
    credit_repaid = summary.credit_received_amount
    credit_repaid_count = summary.credit_received_count
    income = sales_received + credit_repaid
    net_change = income - total_withdrawn

    opening_balance = _register_balance(session, start - dt.timedelta(days=1))
    closing_balance = opening_balance + net_change
    active_credit_count, active_credit_amount = _active_credit_balance(session, end)
    forgiven_by_day = _forgiven_by_day(session, start, end)
    forgiven_amount = sum((amount for amount, _count in forgiven_by_day.values()), Decimal("0"))
    forgiven_count = sum((count for _amount, count in forgiven_by_day.values()), 0)

    # per-day aggregation
    day_count: dict[dt.date, int] = defaultdict(int)
    day_sales_total: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    day_sales_received: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    day_new_credits: dict[dt.date, int] = defaultdict(int)
    day_credit_repaid: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    day_credit_repaid_count: dict[dt.date, int] = defaultdict(int)
    day_withdrawn: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))

    for d in details:
        day_count[d.txn.date] += 1
        day_sales_total[d.txn.date] += d.total
        day_sales_received[d.txn.date] += d.txn.amount_received
        if d.credit is not None:
            day_new_credits[d.txn.date] += 1
    for w in withdrawals:
        day_withdrawn[w.date] += w.amount
    payments = list(
        session.exec(
            select(CreditPayment)
            .where(CreditPayment.date >= start)
            .where(CreditPayment.date <= end)
        ).all()
    )
    for p in payments:
        day_credit_repaid[p.date] += p.amount
        day_credit_repaid_count[p.date] += 1

    all_dates = (
        set(day_count)
        | set(day_withdrawn)
        | set(day_credit_repaid)
        | set(forgiven_by_day)
    )
    ordered_dates = sorted(all_dates)
    running_balance = opening_balance
    days_asc: list[DayStat] = []
    for date in ordered_dates:
        opening = running_balance
        stat = DayStat(
            date=date,
            txn_count=day_count[date],
            sales_total=day_sales_total[date],
            sales_received=day_sales_received[date],
            new_credit_count=day_new_credits[date],
            credit_repaid=day_credit_repaid[date],
            credit_repaid_count=day_credit_repaid_count[date],
            withdrawn=day_withdrawn[date],
            opening_balance=opening,
            closing_balance=opening + day_sales_received[date] + day_credit_repaid[date] - day_withdrawn[date],
            forgiven_amount=forgiven_by_day[date][0],
            forgiven_count=forgiven_by_day[date][1],
        )
        running_balance = stat.closing_balance
        days_asc.append(stat)

    return ReportData(
        start=start,
        end=end,
        summary=summary,
        opening_balance=opening_balance,
        sales_received=sales_received,
        credit_repaid=credit_repaid,
        credit_repaid_count=credit_repaid_count,
        total_withdrawn=total_withdrawn,
        net_change=net_change,
        closing_balance=closing_balance,
        active_credit_count=active_credit_count,
        active_credit_amount=active_credit_amount,
        forgiven_amount=forgiven_amount,
        forgiven_count=forgiven_count,
        days=list(reversed(days_asc)),
    )


def last_day_of_month(d: dt.date) -> dt.date:
    """Return the last calendar day of d's month."""
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - dt.timedelta(days=1)


def _register_balance(session: Session, through: dt.date) -> Decimal:
    sales = sum(
        (
            t.amount_received
            for t in session.exec(
                select(Transaction).where(Transaction.date <= through)
            ).all()
        ),
        Decimal("0"),
    )
    repaid = sum(
        (
            p.amount
            for p in session.exec(
                select(CreditPayment).where(CreditPayment.date <= through)
            ).all()
        ),
        Decimal("0"),
    )
    withdrawn = sum(
        (
            w.amount
            for w in session.exec(
                select(CashWithdrawal).where(CashWithdrawal.date <= through)
            ).all()
        ),
        Decimal("0"),
    )
    return sales + repaid - withdrawn


def _active_credit_balance(session: Session, through: dt.date) -> tuple[int, Decimal]:
    credits = list(
        session.exec(select(Credit).where(Credit.date <= through)).all()
    )
    if not credits:
        return 0, Decimal("0")
    credit_ids = [c.id for c in credits if c.id is not None]
    paid_by_credit: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    if credit_ids:
        payments = session.exec(
            select(CreditPayment)
            .where(CreditPayment.credit_id.in_(credit_ids))
            .where(CreditPayment.date <= through)
        ).all()
        for p in payments:
            paid_by_credit[p.credit_id] += p.amount

    count = 0
    total = Decimal("0")
    for credit in credits:
        if (
            credit.status == CreditStatus.forgiven
            and credit.forgiven_at
            and clock.to_local(credit.forgiven_at).date() <= through
        ):
            continue
        remaining = credit.original_amount - paid_by_credit[credit.id]
        if remaining > 0:
            count += 1
            total += remaining
    return count, total


def _forgiven_by_day(
    session: Session, start: dt.date, end: dt.date
) -> dict[dt.date, tuple[Decimal, int]]:
    forgiven = [
        credit
        for credit in session.exec(
            select(Credit).where(Credit.status == CreditStatus.forgiven)
        ).all()
        if credit.forgiven_at
        and start <= clock.to_local(credit.forgiven_at).date() <= end
    ]
    if not forgiven:
        return defaultdict(lambda: (Decimal("0"), 0))

    credit_ids = [c.id for c in forgiven if c.id is not None]
    paid_by_credit: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    if credit_ids:
        payments = session.exec(
            select(CreditPayment).where(CreditPayment.credit_id.in_(credit_ids))
        ).all()
        for p in payments:
            paid_by_credit[p.credit_id] += p.amount

    result: dict[dt.date, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
    for credit in forgiven:
        date = clock.to_local(credit.forgiven_at).date()
        amount, count = result[date]
        result[date] = (
            amount + credit.original_amount - paid_by_credit[credit.id],
            count + 1,
        )
    return result
