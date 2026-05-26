"""Dashboard service — visual summary aggregates for the dashboards screen."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session

from kodak.models.enums import ProductCategory
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
        key=lambda row: (row.qty, row.revenue, row.label),
        reverse=True,
    )[:5]

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
