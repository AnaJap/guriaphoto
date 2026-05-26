"""Generic key-value settings store.

Holds studio profile, currency symbol, credit-code format, and Mamuka's
commission tariffs (photo 5%, passport 30%, enlargement 20%). Values are
stored as JSON text so complex settings don't need schema migrations.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
