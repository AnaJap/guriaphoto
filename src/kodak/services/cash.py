"""Cash withdrawal service — log and query daily register withdrawals."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlmodel import Session, select

from kodak.access import require_write_access
from kodak.models.cash import CashWithdrawal
from kodak.models.credit import CreditPayment
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
    """Sum of amount_received across all transactions for a date (sales only)."""
    txns = list(session.exec(select(Transaction).where(Transaction.date == date)).all())
    return sum(t.amount_received for t in txns) or Decimal("0")


def day_income(session: Session, date: dt.date) -> Decimal:
    """Actual cash taken in on a date: sale payments + credit (ნისია) repayments."""
    sales = sum(
        (t.amount_received
         for t in session.exec(select(Transaction).where(Transaction.date == date)).all()),
        Decimal("0"),
    )
    repaid = sum(
        (p.amount
         for p in session.exec(select(CreditPayment).where(CreditPayment.date == date)).all()),
        Decimal("0"),
    )
    return sales + repaid


def register_balance(session: Session, through: dt.date) -> Decimal:
    """Cumulative cash in the register at the end of ``through``.

    All income (sale payments + credit repayments) minus all withdrawals, for
    every date up to and including ``through`` — i.e. what should physically be
    in the till that evening, carried over from prior days plus today's moves.
    """
    sales = sum(
        (t.amount_received
         for t in session.exec(
             select(Transaction).where(Transaction.date <= through)
         ).all()),
        Decimal("0"),
    )
    repaid = sum(
        (p.amount
         for p in session.exec(
             select(CreditPayment).where(CreditPayment.date <= through)
         ).all()),
        Decimal("0"),
    )
    withdrawn = sum(
        (w.amount
         for w in session.exec(
             select(CashWithdrawal).where(CashWithdrawal.date <= through)
         ).all()),
        Decimal("0"),
    )
    return sales + repaid - withdrawn
