"""Transaction creation with automatic credit handling.

A transaction is one customer visit. If the customer pays less than the
total (amount_received < sum of line totals), the shortfall is recorded
as a Credit (ნისია) automatically.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from kodak.access import require_write_access
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus
from kodak.models.transaction import LineItem, Transaction
from kodak.services.pricing import compute_line_total, get_product


@dataclass
class LineItemInput:
    product_id: int
    quantity: int


@dataclass
class TransactionResult:
    transaction: Transaction
    line_items: list[LineItem]
    credit: Credit | None


def create_transaction(
    session: Session,
    date: dt.date,
    customer_surname: str,
    items: list[LineItemInput],
    amount_received: Decimal,
    notes: str | None = None,
    created_by_user_id: int | None = None,
) -> TransactionResult:
    require_write_access()
    if not items:
        raise ValueError("A transaction must have at least one line item")

    txn = Transaction(
        date=date,
        customer_surname=customer_surname,
        amount_received=amount_received,
        notes=notes,
        created_by_user_id=created_by_user_id,
    )
    session.add(txn)
    session.flush()  # populate txn.id without committing

    line_items: list[LineItem] = []
    total = Decimal("0")
    for inp in items:
        product = get_product(session, inp.product_id)
        line_total = compute_line_total(product.unit_price, inp.quantity)
        li = LineItem(
            transaction_id=txn.id,
            product_id=inp.product_id,
            quantity=inp.quantity,
            unit_price=product.unit_price,
            line_total=line_total,
        )
        session.add(li)
        line_items.append(li)
        total += line_total

    credit: Credit | None = None
    shortfall = (total - amount_received).quantize(Decimal("0.01"))
    if shortfall > Decimal("0"):
        credit = Credit(
            transaction_id=txn.id,
            date=date,
            customer_surname=customer_surname,
            code=_generate_credit_code(session, date),
            original_amount=shortfall,
            remaining_amount=shortfall,
            status=_initial_credit_status(amount_received),
        )
        session.add(credit)

    session.commit()
    session.refresh(txn)
    for li in line_items:
        session.refresh(li)
    if credit:
        session.refresh(credit)

    return TransactionResult(transaction=txn, line_items=line_items, credit=credit)


def _generate_credit_code(session: Session, date: dt.date) -> str:
    """Sequential code like N-2025-001, N-2025-002, …"""
    prefix = f"N-{date.year}-"
    existing = session.exec(
        select(Credit).where(Credit.code.like(f"{prefix}%"))
    ).all()
    return f"{prefix}{len(existing) + 1:03d}"


def _initial_credit_status(amount_received: Decimal) -> CreditStatus:
    return CreditStatus.partial if amount_received > Decimal("0") else CreditStatus.active


def get_transaction_total(line_items: list[LineItem]) -> Decimal:
    return sum((li.line_total for li in line_items), Decimal("0"))


def update_transaction(
    session: Session,
    txn_id: int,
    *,
    customer_surname: str,
    amount_received: Decimal,
    notes: str | None,
) -> Transaction:
    require_write_access()
    """Edit a transaction's customer name, received amount, and/or notes.

    If *amount_received* changes the linked Credit is recalculated — but only
    when the credit has no existing CreditPayment rows. Raises ValueError
    with a Georgian message when that constraint is violated.
    """
    txn = session.get(Transaction, txn_id)
    if txn is None:
        raise ValueError("გარიგება ვერ მოიძებნა")

    line_items = list(
        session.exec(select(LineItem).where(LineItem.transaction_id == txn_id)).all()
    )
    total = sum(li.line_total for li in line_items) or Decimal("0")

    credit = session.exec(
        select(Credit).where(Credit.transaction_id == txn_id)
    ).first()

    received_changed = amount_received.quantize(Decimal("0.01")) != txn.amount_received.quantize(
        Decimal("0.01")
    )

    if received_changed and credit:
        payments = session.exec(
            select(CreditPayment).where(CreditPayment.credit_id == credit.id)
        ).all()
        if payments:
            raise ValueError(
                "ნისიის გადახდა დაფიქსირებულია — "
                "მიღებული თანხის შეცვლა შეუძლებელია."
            )
        shortfall = (total - amount_received).quantize(Decimal("0.01"))
        if shortfall <= Decimal("0"):
            session.delete(credit)
        else:
            credit.original_amount = shortfall
            credit.remaining_amount = shortfall
            credit.status = _initial_credit_status(amount_received)
            credit.customer_surname = customer_surname
            session.add(credit)

    elif received_changed and not credit:
        shortfall = (total - amount_received).quantize(Decimal("0.01"))
        if shortfall > Decimal("0"):
            session.add(Credit(
                transaction_id=txn_id,
                date=txn.date,
                customer_surname=customer_surname,
                code=_generate_credit_code(session, txn.date),
                original_amount=shortfall,
                remaining_amount=shortfall,
                status=_initial_credit_status(amount_received),
            ))

    elif credit and customer_surname != txn.customer_surname:
        credit.customer_surname = customer_surname
        session.add(credit)

    txn.customer_surname = customer_surname
    txn.amount_received = amount_received
    txn.notes = notes
    session.add(txn)
    session.commit()
    session.refresh(txn)
    return txn


def delete_transaction(session: Session, txn_id: int) -> None:
    require_write_access()
    """Hard-delete a transaction, its line items, and any unpaid credit.

    Raises ValueError (Georgian message) if the linked credit already has
    recorded payments — those cannot be erased without an audit trail.
    """
    txn = session.get(Transaction, txn_id)
    if txn is None:
        raise ValueError("გარიგება ვერ მოიძებნა")

    credit = session.exec(
        select(Credit).where(Credit.transaction_id == txn_id)
    ).first()
    if credit:
        payments = session.exec(
            select(CreditPayment).where(CreditPayment.credit_id == credit.id)
        ).all()
        if payments:
            raise ValueError(
                "ნისიის გადახდა დაფიქსირებულია — "
                "ჩანაწერის წაშლა შეუძლებელია."
            )
        session.delete(credit)

    for li in session.exec(
        select(LineItem).where(LineItem.transaction_id == txn_id)
    ).all():
        session.delete(li)

    session.delete(txn)
    session.commit()
