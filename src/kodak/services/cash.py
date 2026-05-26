"""Cash withdrawal service — log and query daily register withdrawals."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlmodel import Session, select

from kodak.access import require_write_access
from kodak.models.cash import CashWithdrawal
from kodak.models.transaction import Transaction
from kodak.models.user import User


def update_withdrawal(
    session: Session,
    withdrawal_id: int,
    amount: Decimal,
    note: str | None,
) -> CashWithdrawal:
    require_write_access()
    w = session.get(CashWithdrawal, withdrawal_id)
    w.amount = amount
    w.note = note
    session.commit()
    session.refresh(w)
    return w


def delete_withdrawal(session: Session, withdrawal_id: int) -> None:
    require_write_access()
    w = session.get(CashWithdrawal, withdrawal_id)
    if w:
        session.delete(w)
        session.commit()


def log_withdrawal(
    session: Session,
    user_id: int,
    date: dt.date,
    amount: Decimal,
    note: str | None = None,
) -> CashWithdrawal:
    require_write_access()
    w = CashWithdrawal(date=date, user_id=user_id, amount=amount, note=note)
    session.add(w)
    session.commit()
    session.refresh(w)
    return w


def list_day_withdrawals(
    session: Session, date: dt.date
) -> list[tuple[CashWithdrawal, User]]:
    """Return all withdrawals for a date, oldest first, with the User who made them."""
    withdrawals = list(
        session.exec(
            select(CashWithdrawal)
            .where(CashWithdrawal.date == date)
            .order_by(CashWithdrawal.created_at)
        ).all()
    )
    if not withdrawals:
        return []
    user_ids = {w.user_id for w in withdrawals}
    users = {
        u.id: u
        for u in session.exec(select(User).where(User.id.in_(user_ids))).all()
    }
    return [(w, users[w.user_id]) for w in withdrawals if w.user_id in users]


def day_revenue(session: Session, date: dt.date) -> Decimal:
    """Sum of amount_received across all transactions for a date."""
    txns = list(session.exec(select(Transaction).where(Transaction.date == date)).all())
    return sum(t.amount_received for t in txns) or Decimal("0")
