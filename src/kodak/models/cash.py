"""Daily cash withdrawals per employee (row 39 of each day block)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlmodel import Field, SQLModel


class CashWithdrawal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    amount: Decimal = Field(max_digits=10, decimal_places=2)
    note: str | None = Field(default=None)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
