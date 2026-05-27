"""Dashboard service — visual summary aggregates for the dashboards screen."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from kodak import clock
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, ProductCategory
from kodak.services.history import list_range_transactions, summarize_range


@dataclass(frozen=True)
class ProductRank:
    label: str
    qty: int
    revenue: Decimal


@dataclass(frozen=True)
class CategoryRank:
    category: ProductCategory
    qty: int
    revenue: Decimal


@dataclass(frozen=True)
class DayPoint:
    date: dt.date
    txn_count: int
    revenue: Decimal

    @property
    def avg_ticket(self) -> Decimal:
        if self.txn_count <= 0:
            return Decimal("0.00")
        return (self.revenue / Decimal(self.txn_count)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class DashboardData:
    start: dt.date
    end: dt.date
    total_txns: int
    total_revenue: Decimal
    avg_ticket: Decimal
    active_days: int
    top_products: list[ProductRank]
    category_breakdown: list[CategoryRank]
    daily: list[DayPoint]


def build_dashboard(session: Session, start: dt.date, end: dt.date) -> DashboardData:
    details = list_range_transactions(session, start, end)
    summary = summarize_range(details)

    product_qty: dict[str, int] = defaultdict(int)
    product_rev: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    day_txns: dict[dt.date, int] = defaultdict(int)
    day_rev: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))

    for detail in details:
        day_txns[detail.txn.date] += 1
        day_rev[detail.txn.date] += detail.total
        for line_item, product in detail.items:
            label = f"{product.name} {product.size_label or ''}".strip()
            product_qty[label] += line_item.quantity
            product_rev[label] += line_item.line_total

    top_products = sorted(
        [
            ProductRank(label=label, qty=product_qty[label], revenue=product_rev[label])
            for label in product_qty
        ],
        key=lambda row: (row.revenue, row.qty, row.label),
        reverse=True,
    )[:10]

    category_breakdown = [
        CategoryRank(category=cat.category, qty=cat.qty, revenue=cat.revenue)
        for cat in summary.categories
    ]

    total_days = max((end - start).days, 0) + 1
    daily = []
    active_days = 0
    for offset in range(total_days):
        date = start + dt.timedelta(days=offset)
        point = DayPoint(
            date=date,
            txn_count=day_txns[date],
            revenue=day_rev[date],
        )
        if point.txn_count > 0:
            active_days += 1
        daily.append(point)

    if summary.total_txns > 0:
        avg_ticket = (summary.total_revenue / Decimal(summary.total_txns)).quantize(
            Decimal("0.01")
        )
    else:
        avg_ticket = Decimal("0.00")

    return DashboardData(
        start=start,
        end=end,
        total_txns=summary.total_txns,
        total_revenue=summary.total_revenue,
        avg_ticket=avg_ticket,
        active_days=active_days,
        top_products=top_products,
        category_breakdown=category_breakdown,
        daily=daily,
    )


# ── credit (ნისია) movement ────────────────────────────────────────────────

@dataclass(frozen=True)
class CreditDayPoint:
    date: dt.date
    issued: Decimal      # new credit extended that day
    repaid: Decimal      # repayments collected that day


@dataclass(frozen=True)
class CreditMovement:
    start: dt.date
    end: dt.date
    issued_amount: Decimal
    issued_count: int
    repaid_amount: Decimal
    repaid_count: int
    forgiven_amount: Decimal
    forgiven_count: int
    outstanding_now: Decimal     # current unpaid balance across all open credits
    daily: list[CreditDayPoint]


def build_credit_movement(session: Session, start: dt.date, end: dt.date) -> CreditMovement:
    issued_credits = list(
        session.exec(
            select(Credit).where(Credit.date >= start).where(Credit.date <= end)
        ).all()
    )
    payments = list(
        session.exec(
            select(CreditPayment)
            .where(CreditPayment.date >= start)
            .where(CreditPayment.date <= end)
        ).all()
    )

    issued_amount = sum((c.original_amount for c in issued_credits), Decimal("0"))
    repaid_amount = sum((p.amount for p in payments), Decimal("0"))

    # Forgiven this period — forgiven_at is UTC, compare in GMT+4.
    forgiven = [
        c
        for c in session.exec(
            select(Credit).where(Credit.status == CreditStatus.forgiven)
        ).all()
        if c.forgiven_at and start <= clock.to_local(c.forgiven_at).date() <= end
    ]
    forgiven_writeoff = Decimal("0")
    if forgiven:
        paid: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        ids = [c.id for c in forgiven]
        for p in session.exec(
            select(CreditPayment).where(CreditPayment.credit_id.in_(ids))
        ).all():
            paid[p.credit_id] += p.amount
        forgiven_writeoff = sum(
            (c.original_amount - paid[c.id] for c in forgiven), Decimal("0")
        )

    outstanding_now = sum(
        (
            c.remaining_amount
            for c in session.exec(
                select(Credit).where(
                    Credit.status.in_([CreditStatus.active, CreditStatus.partial])
                )
            ).all()
        ),
        Decimal("0"),
    )

    issued_by_day: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    repaid_by_day: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    for c in issued_credits:
        issued_by_day[c.date] += c.original_amount
    for p in payments:
        repaid_by_day[p.date] += p.amount

    daily = [
        CreditDayPoint(
            date=start + dt.timedelta(days=offset),
            issued=issued_by_day[start + dt.timedelta(days=offset)],
            repaid=repaid_by_day[start + dt.timedelta(days=offset)],
        )
        for offset in range(max((end - start).days, 0) + 1)
    ]

    return CreditMovement(
        start=start,
        end=end,
        issued_amount=issued_amount,
        issued_count=len(issued_credits),
        repaid_amount=repaid_amount,
        repaid_count=len(payments),
        forgiven_amount=forgiven_writeoff,
        forgiven_count=len(forgiven),
        outstanding_now=outstanding_now,
        daily=daily,
    )
