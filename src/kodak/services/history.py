"""Daily / range transaction history queries."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, ProductCategory
from kodak.models.product import Product
from kodak.models.transaction import LineItem, Transaction


@dataclass
class TxnDetail:
    txn: Transaction
    items: list[tuple[LineItem, Product]]
    credit: Credit | None
    total: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class CategoryStat:
    category: ProductCategory
    qty: int
    revenue: Decimal


@dataclass
class RangeSummary:
    total_txns: int                  # number of sales in the period
    total_revenue: Decimal           # gross value of all sales
    received_from_sales: Decimal     # cash taken in at point-of-sale
    new_credit_count: int            # new ნისია opened in the period
    open_credit_count: int
    open_credit_amount: Decimal
    categories: list[CategoryStat]   # sorted by revenue desc
    # Credit repayments collected in the period (set by summarize_range when a
    # session is supplied; otherwise zero).
    credit_received_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    credit_received_count: int = 0

    @property
    def cashier_received(self) -> Decimal:
        """Total cash into the till: sale payments + credit repayments."""
        return self.received_from_sales + self.credit_received_amount


# ──────────────────────────────────────────────────────── queries

def list_range_transactions(
    session: Session, start: dt.date, end: dt.date
) -> list[TxnDetail]:
    """Return all transactions between start..end (inclusive), newest first."""
    txns = list(
        session.exec(
            select(Transaction)
            .where(Transaction.date >= start)
            .where(Transaction.date <= end)
            .order_by(Transaction.created_at.desc())
        ).all()
    )
    if not txns:
        return []

    txn_ids = [t.id for t in txns]

    all_items = list(
        session.exec(select(LineItem).where(LineItem.transaction_id.in_(txn_ids))).all()
    )

    product_ids = {item.product_id for item in all_items}
    products: dict[int, Product] = {}
    if product_ids:
        products = {
            p.id: p
            for p in session.exec(select(Product).where(Product.id.in_(product_ids))).all()
        }

    credits = {
        c.transaction_id: c
        for c in session.exec(
            select(Credit).where(Credit.transaction_id.in_(txn_ids))
        ).all()
    }

    items_by_txn: dict[int, list[tuple[LineItem, Product]]] = defaultdict(list)
    for item in all_items:
        if item.product_id in products:
            items_by_txn[item.transaction_id].append((item, products[item.product_id]))

    result = []
    for txn in txns:
        pairs = items_by_txn[txn.id]
        total = sum(li.line_total for li, _ in pairs) or Decimal("0")
        result.append(TxnDetail(txn=txn, items=pairs, credit=credits.get(txn.id), total=total))

    return result


def list_day_transactions(session: Session, date: dt.date) -> list[TxnDetail]:
    """Convenience wrapper for a single day."""
    return list_range_transactions(session, date, date)


def summarize_range(
    details: list[TxnDetail],
    *,
    session: Session | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> RangeSummary:
    """Aggregate a list of TxnDetail into summary metrics.

    If ``session``/``start``/``end`` are supplied, credit-repayment totals for
    the period are also computed (``credit_received_amount/_count`` and the
    ``cashier_received`` property). Callers that don't need those can omit them.
    """
    total_revenue = sum(d.total for d in details) or Decimal("0")
    received_from_sales = sum(d.txn.amount_received for d in details) or Decimal("0")
    new_credit_count = sum(1 for d in details if d.credit is not None)

    open_credits = [
        d.credit for d in details
        if d.credit and d.credit.status != CreditStatus.cleared
    ]
    open_credit_amount = (
        sum(c.remaining_amount for c in open_credits) or Decimal("0")
    )

    cat_qty: dict[ProductCategory, int] = defaultdict(int)
    cat_rev: dict[ProductCategory, Decimal] = defaultdict(lambda: Decimal("0"))
    for d in details:
        for li, prod in d.items:
            cat_qty[prod.category] += li.quantity
            cat_rev[prod.category] += li.line_total

    categories = sorted(
        [CategoryStat(cat, cat_qty[cat], cat_rev[cat]) for cat in cat_qty],
        key=lambda c: c.revenue,
        reverse=True,
    )

    credit_received_amount = Decimal("0")
    credit_received_count = 0
    if session is not None and start is not None and end is not None:
        payments = list(
            session.exec(
                select(CreditPayment)
                .where(CreditPayment.date >= start)
                .where(CreditPayment.date <= end)
            ).all()
        )
        credit_received_amount = sum((p.amount for p in payments), Decimal("0"))
        credit_received_count = len(payments)

    return RangeSummary(
        total_txns=len(details),
        total_revenue=total_revenue,
        received_from_sales=received_from_sales,
        new_credit_count=new_credit_count,
        open_credit_count=len(open_credits),
        open_credit_amount=open_credit_amount,
        categories=categories,
        credit_received_amount=credit_received_amount,
        credit_received_count=credit_received_count,
    )
