"""Customer credits (ნისია) and repayments."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlmodel import Field, SQLModel

from kodak.models.enums import CreditStatus


class Credit(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    transaction_id: int = Field(foreign_key="transaction.id", unique=True, index=True)
    date: dt.date = Field(index=True)
    customer_surname: str = Field(index=True)
    code: str = Field(index=True)
    original_amount: Decimal = Field(max_digits=10, decimal_places=2)
    remaining_amount: Decimal = Field(max_digits=10, decimal_places=2)
    status: CreditStatus = Field(default=CreditStatus.active, index=True)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    # Forgiveness tracking (populated only when status == forgiven)
    forgiven_at: dt.datetime | None = Field(default=None)
    forgiven_by_user_id: int | None = Field(default=None, foreign_key="user.id", index=True)


class CreditPayment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    credit_id: int = Field(foreign_key="credit.id", index=True)
    date: dt.date = Field(index=True)
    amount: Decimal = Field(max_digits=10, decimal_places=2)
    notes: str | None = Field(default=None)
    created_by_user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
