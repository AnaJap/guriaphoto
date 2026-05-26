"""PIN-based authentication and user bootstrap."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from sqlmodel import Session, select

from kodak.access import require_write_access
from kodak.models.enums import Role
from kodak.models.user import User


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(session: Session, username: str, pin: str) -> User | None:
    user = session.exec(select(User).where(User.username == username, User.active == True)).first()
    if user and user.pin_hash == _hash_pin(pin):
        return user
    return None


def create_user(
    session: Session,
    username: str,
    pin: str,
    full_name: str,
    role: Role = Role.employee,
    fixed_salary: Decimal | None = None,
) -> User:
    require_write_access()
    user = User(
        username=username,
        pin_hash=_hash_pin(pin),
        full_name=full_name,
        role=role,
        fixed_salary=fixed_salary,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def seed_users(session: Session) -> None:
    """Insert or patch the known studio staff.

    Creates missing users and updates any whose full_name is still the
    old English placeholder so a live DB gets the Georgian names immediately.
    """
    require_write_access()
    defaults = [
        ("archil",  "0000", "არჩილი", Role.admin,    None),
        ("mamuka",  "0000", "მამუკა",  Role.employee, Decimal("800")),
        ("khatuna", "0000", "ხათუნა", Role.employee, Decimal("800")),
    ]
    existing: dict[str, User] = {
        u.username: u for u in session.exec(select(User)).all()
    }
    for username, pin, full_name, role, salary in defaults:
        if username not in existing:
            create_user(session, username, pin, full_name, role, salary)
        else:
            user = existing[username]
            if user.full_name != full_name:
                user.full_name = full_name
                session.add(user)
    session.commit()
