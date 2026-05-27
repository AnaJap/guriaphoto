"""Credit (ნისია) payment recording, status management, and forgiveness."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_
from sqlmodel import Session, select

from kodak.access import require_write_access
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus
from kodak.models.transaction import LineItem, Transaction

# Statuses that represent an outstanding balance (shown in stats / open list)
_OPEN_STATUSES = (CreditStatus.active, CreditStatus.partial)


@dataclass(frozen=True)
class CreditSaleAmounts:
    sale_total: Decimal
    initial_paid: Decimal


@dataclass(frozen=True)
class CreditPaymentDisplayRow:
    credit: Credit
    date: dt.date
    amount: Decimal
    created_at: dt.datetime
    notes: str | None = None
    payment: CreditPayment | None = None
    label: str | None = None


def record_payment(
    session: Session,
    credit_id: int,
    amount: Decimal,
    date_paid,
    notes: str | None = None,
    created_by_user_id: int | None = None,
) -> CreditPayment:
    require_write_access()
    credit = session.get(Credit, credit_id)
    if credit is None:
        raise ValueError(f"Credit {credit_id} not found")
    if credit.status not in _OPEN_STATUSES:
        raise ValueError("Credit is already closed (cleared or forgiven)")
    if amount <= Decimal("0"):
        raise ValueError("Payment amount must be positive")
    if amount > credit.remaining_amount:
        raise ValueError(
            f"Payment {amount} exceeds remaining balance {credit.remaining_amount}"
        )

    payment = CreditPayment(
        credit_id=credit_id,
        date=date_paid,
        amount=amount,
        notes=notes,
        created_by_user_id=created_by_user_id,
    )
    session.add(payment)

    credit.remaining_amount = (credit.remaining_amount - amount).quantize(Decimal("0.01"))
    if credit.remaining_amount == Decimal("0"):
        credit.status = CreditStatus.cleared
    else:
        credit.status = CreditStatus.partial

    session.add(credit)
    session.commit()
    session.refresh(payment)
    session.refresh(credit)
    return payment


def forgive_credit(
    session: Session,
    credit_id: int,
    forgiven_by_user_id: int | None = None,
) -> Credit:
    """Pardon the remaining balance — admin-only action."""
    require_write_access()
    credit = session.get(Credit, credit_id)
    if credit is None:
        raise ValueError(f"Credit {credit_id} not found")
    if credit.status not in _OPEN_STATUSES:
        raise ValueError("Only open credits can be forgiven")

    credit.status = CreditStatus.forgiven
    credit.remaining_amount = Decimal("0.00")
    credit.forgiven_at = dt.datetime.now(dt.UTC)
    credit.forgiven_by_user_id = forgiven_by_user_id

    session.add(credit)
    session.commit()
    session.refresh(credit)
    return credit


def update_credit_payment(
    session: Session,
    payment_id: int,
    *,
    amount: Decimal,
    date_paid,
    notes: str | None = None,
) -> Credit:
    """Correct an existing credit payment and resync the credit balance."""
    require_write_access()
    payment = session.get(CreditPayment, payment_id)
    if payment is None:
        raise ValueError("გადახდა ვერ მოიძებნა")
    credit = session.get(Credit, payment.credit_id)
    if credit is None:
        raise ValueError("ნისია ვერ მოიძებნა")
    if amount <= Decimal("0"):
        raise ValueError("თანხა დადებითი უნდა იყოს")

    amount = amount.quantize(Decimal("0.01"))
    other_total = _payments_total(session, credit.id, exclude_payment_id=payment.id)
    if other_total + amount > credit.original_amount:
        raise ValueError("გადახდების ჯამი მეტია ნისიის თანხაზე")

    payment.amount = amount
    payment.date = date_paid
    payment.notes = notes
    session.add(payment)
    session.flush()

    _sync_credit_balance(session, credit, preserve_forgiven=credit.status == CreditStatus.forgiven)
    session.commit()
    session.refresh(credit)
    return credit


def delete_credit_payment(session: Session, payment_id: int) -> Credit:
    """Remove a mistaken credit payment and resync the credit balance."""
    require_write_access()
    payment = session.get(CreditPayment, payment_id)
    if payment is None:
        raise ValueError("გადახდა ვერ მოიძებნა")
    credit = session.get(Credit, payment.credit_id)
    if credit is None:
        raise ValueError("ნისია ვერ მოიძებნა")

    preserve_forgiven = credit.status == CreditStatus.forgiven
    session.delete(payment)
    session.flush()
    _sync_credit_balance(session, credit, preserve_forgiven=preserve_forgiven)
    session.commit()
    session.refresh(credit)
    return credit


def reopen_forgiven_credit(session: Session, credit_id: int) -> Credit:
    """Undo forgiveness and restore the unpaid balance based on payment history."""
    require_write_access()
    credit = session.get(Credit, credit_id)
    if credit is None:
        raise ValueError("ნისია ვერ მოიძებნა")
    if credit.status != CreditStatus.forgiven:
        raise ValueError("მხოლოდ ნაპატიები ნისიის გახსნა შეიძლება")

    credit.forgiven_at = None
    credit.forgiven_by_user_id = None
    _sync_credit_balance(session, credit, preserve_forgiven=False)
    session.commit()
    session.refresh(credit)
    return credit


def _payments_total(
    session: Session,
    credit_id: int,
    *,
    exclude_payment_id: int | None = None,
) -> Decimal:
    q = select(CreditPayment).where(CreditPayment.credit_id == credit_id)
    if exclude_payment_id is not None:
        q = q.where(CreditPayment.id != exclude_payment_id)
    payments = session.exec(q).all()
    return sum((p.amount for p in payments), Decimal("0")).quantize(Decimal("0.01"))


def _sync_credit_balance(
    session: Session,
    credit: Credit,
    *,
    preserve_forgiven: bool,
) -> None:
    paid_total = _payments_total(session, credit.id)
    if preserve_forgiven:
        credit.remaining_amount = Decimal("0.00")
        credit.status = CreditStatus.forgiven
        session.add(credit)
        return

    remaining = (credit.original_amount - paid_total).quantize(Decimal("0.01"))
    if remaining <= Decimal("0"):
        credit.remaining_amount = Decimal("0.00")
        credit.status = CreditStatus.cleared
    else:
        credit.remaining_amount = remaining
        credit.status = (
            CreditStatus.partial
            if paid_total > Decimal("0") or _has_initial_payment(session, credit)
            else CreditStatus.active
        )
    session.add(credit)


def _has_initial_payment(session: Session, credit: Credit) -> bool:
    txn = session.get(Transaction, credit.transaction_id)
    return txn is not None and txn.amount_received > Decimal("0")


def list_open_credits(session: Session) -> list[Credit]:
    """Active + partial credits only (not cleared, not forgiven)."""
    return list(
        session.exec(
            select(Credit)
            .where(Credit.status.in_([s.value for s in _OPEN_STATUSES]))
            .order_by(Credit.date)
        ).all()
    )


def sync_initial_credit_statuses(session: Session) -> int:
    """Mark initial partial-payment credits as partial.

    Older records may have a credit for the unpaid balance while the linked
    transaction already had a payment. Those are still open credits, but they
    should be shown as partially paid instead of totally unpaid.
    """
    require_write_access()
    changed = 0
    credits = session.exec(
        select(Credit).where(Credit.status.in_([s.value for s in _OPEN_STATUSES]))
    ).all()
    for credit in credits:
        has_credit_payments = session.exec(
            select(CreditPayment.id).where(CreditPayment.credit_id == credit.id)
        ).first()
        if has_credit_payments:
            continue

        target = (
            CreditStatus.partial
            if _has_initial_payment(session, credit)
            else CreditStatus.active
        )
        if credit.status != target:
            credit.status = target
            session.add(credit)
            changed += 1

    if changed:
        session.commit()
    return changed


def list_credits_by_filter(
    session: Session,
    status_filter: str | list[CreditStatus] | tuple[CreditStatus, ...] | set[CreditStatus] = "active",
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    search: str = "",
) -> list[Credit]:
    """Return credits matching *status_filter*.

    filter values:
      "all"      — every credit
      "active"   — unpaid active credits
      "open"     — active + partial (legacy alias)
      "partial"  — partially paid
      "cleared"  — fully paid
      "forgiven" — admin write-off
    """
    q = select(Credit)
    if not isinstance(status_filter, str):
        statuses = [status.value for status in status_filter]
        if not statuses:
            return []
        q = q.where(Credit.status.in_(statuses))
    elif status_filter == "all":
        pass
    elif status_filter == "open":
        q = q.where(Credit.status.in_([s.value for s in _OPEN_STATUSES]))
    elif status_filter == "active":
        q = q.where(Credit.status == CreditStatus.active)
    elif status_filter == "partial":
        q = q.where(Credit.status == CreditStatus.partial)
    elif status_filter == "cleared":
        q = q.where(Credit.status == CreditStatus.cleared)
    elif status_filter == "forgiven":
        q = q.where(Credit.status == CreditStatus.forgiven)

    if start_date is not None:
        q = q.where(Credit.date >= start_date)
    if end_date is not None:
        q = q.where(Credit.date <= end_date)

    query = search.strip()
    if query:
        pattern = f"%{query}%"
        q = q.where(or_(Credit.customer_surname.like(pattern), Credit.code.like(pattern)))

    return list(session.exec(q.order_by(Credit.date.desc())).all())


def list_credit_payments_by_filter(
    session: Session,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    search: str = "",
) -> list[CreditPaymentDisplayRow]:
    """Return actual repayment rows with their credit, filtered by date/search."""
    q = select(CreditPayment)
    if start_date is not None:
        q = q.where(CreditPayment.date >= start_date)
    if end_date is not None:
        q = q.where(CreditPayment.date <= end_date)

    payment_rows = list(
        session.exec(
            q.order_by(CreditPayment.date.desc(), CreditPayment.created_at.desc())
        ).all()
    )
    if not payment_rows:
        return []

    credit_ids = {p.credit_id for p in payment_rows}
    credits = {
        c.id: c
        for c in session.exec(select(Credit).where(Credit.id.in_(credit_ids))).all()
    }

    rows: list[CreditPaymentDisplayRow] = [
        CreditPaymentDisplayRow(
            credit=credits[p.credit_id],
            date=p.date,
            amount=p.amount,
            created_at=p.created_at,
            notes=p.notes,
            payment=p,
        )
        for p in payment_rows
        if p.credit_id in credits
    ]

    query = search.strip().lower().replace(",", ".")

    def amount_matches(amount: Decimal) -> bool:
        fixed = f"{amount:.2f}"
        compact = fixed.rstrip("0").rstrip(".")
        return query in fixed or query in compact

    def matches(row: CreditPaymentDisplayRow) -> bool:
        return (
            not query
            or query in row.credit.customer_surname.lower()
            or query in row.credit.code.lower()
            or query in (row.notes or "").lower()
            or amount_matches(row.amount)
        )

    return sorted(
        (row for row in rows if matches(row)),
        key=lambda row: (row.date, row.created_at),
        reverse=True,
    )


def list_all_credits(session: Session, *, include_cleared: bool = False) -> list[Credit]:
    """Legacy helper kept for compatibility with history/report views."""
    q = select(Credit)
    if not include_cleared:
        q = q.where(Credit.status.in_([s.value for s in _OPEN_STATUSES]))
    return list(session.exec(q.order_by(Credit.date)).all())


def list_payments_for_credit(session: Session, credit_id: int) -> list[CreditPayment]:
    return list(
        session.exec(
            select(CreditPayment)
            .where(CreditPayment.credit_id == credit_id)
            .order_by(CreditPayment.date)
        ).all()
    )


def list_payments_for_credits(
    session: Session,
    credit_ids: list[int],
) -> dict[int, list[CreditPayment]]:
    """Return payment rows grouped by credit id for list previews."""
    if not credit_ids:
        return {}

    rows = list(
        session.exec(
            select(CreditPayment)
            .where(CreditPayment.credit_id.in_(credit_ids))
            .order_by(CreditPayment.date.desc(), CreditPayment.created_at.desc())
        ).all()
    )
    grouped: dict[int, list[CreditPayment]] = {credit_id: [] for credit_id in credit_ids}
    for payment in rows:
        grouped.setdefault(payment.credit_id, []).append(payment)
    return grouped


def list_credit_sale_amounts(
    session: Session,
    credits: list[Credit],
) -> dict[int, CreditSaleAmounts]:
    """Return original sale totals and initial paid amounts for credit display."""
    credits_by_txn = {
        credit.transaction_id: credit
        for credit in credits
        if credit.id is not None
    }
    if not credits_by_txn:
        return {}

    txns = list(
        session.exec(
            select(Transaction).where(Transaction.id.in_(credits_by_txn.keys()))
        ).all()
    )
    line_items = list(
        session.exec(
            select(LineItem).where(LineItem.transaction_id.in_(credits_by_txn.keys()))
        ).all()
    )
    totals_by_txn: dict[int, Decimal] = {}
    for item in line_items:
        totals_by_txn[item.transaction_id] = (
            totals_by_txn.get(item.transaction_id, Decimal("0")) + item.line_total
        )

    result: dict[int, CreditSaleAmounts] = {}
    for txn in txns:
        credit = credits_by_txn.get(txn.id)
        if credit is None or credit.id is None:
            continue
        fallback_total = (txn.amount_received + credit.original_amount).quantize(
            Decimal("0.01")
        )
        sale_total = totals_by_txn.get(txn.id, fallback_total).quantize(Decimal("0.01"))
        result[credit.id] = CreditSaleAmounts(
            sale_total=sale_total,
            initial_paid=txn.amount_received.quantize(Decimal("0.01")),
        )
    return result
