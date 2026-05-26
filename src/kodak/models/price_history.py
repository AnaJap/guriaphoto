"""Product price-change audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel


class ProductPriceHistory(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    old_price: Decimal = Field(max_digits=10, decimal_places=2)
    new_price: Decimal = Field(max_digits=10, decimal_places=2)
    changed_by_user_id: int | None = Field(
        default=None, foreign_key="user.id", index=True
    )
    changed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
