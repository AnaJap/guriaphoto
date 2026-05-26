"""Stock items and monthly movements.

Sales are not stored on the movement row — they are computed by summing
line-item quantities for products linked to this stock item in the
month. Only opening / purchases / closing are persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from kodak.models.enums import StockCategory


class StockItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    category: StockCategory = Field(index=True)
    name: str
    size_label: str | None = Field(default=None)
    unit: str = Field(default="pc")
    low_threshold: int | None = Field(default=None)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StockMovement(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("stock_item_id", "year", "month", name="uq_stockmove_item_period"),
    )

    id: int | None = Field(default=None, primary_key=True)
    stock_item_id: int = Field(foreign_key="stockitem.id", index=True)
    year: int = Field(index=True)
    month: int = Field(ge=1, le=12, index=True)
    opening: int = Field(default=0)
    purchases: int = Field(default=0)
    closing: int = Field(default=0)
