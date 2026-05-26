"""User accounts — Archil (admin), Mamuka, Khatuna (employees)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from kodak.models.enums import Role


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    pin_hash: str
    full_name: str
    role: Role = Field(default=Role.employee, index=True)
    fixed_salary: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
