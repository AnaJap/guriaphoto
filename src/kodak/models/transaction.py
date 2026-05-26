"""Transactions and their line items.

A Transaction is one customer visit on a given day. Each LineItem captures
a quantity of one Product at the price in effect at entry time
(``unit_price`` is a snapshot, not a foreign-key lookup).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlmodel import Field, SQLModel


class Transaction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    customer_surname: str = Field(index=True)
    amount_received: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=2)
    notes: str | None = Field(default=None)
    created_by_user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))


class LineItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    quantity: int = Field(ge=0)
    unit_price: Decimal = Field(max_digits=10, decimal_places=2)
    line_total: Decimal = Field(max_digits=10, decimal_places=2)
