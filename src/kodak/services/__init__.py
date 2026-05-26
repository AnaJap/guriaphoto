"""Business logic layer — sits between UI and models."""

from kodak.services.auth import create_user, seed_users, verify_pin
from kodak.services.credits import list_open_credits, record_payment
from kodak.services.pricing import compute_line_total, get_product, list_active_products
from kodak.services.transactions import LineItemInput, TransactionResult, create_transaction

__all__ = [
    "LineItemInput",
    "TransactionResult",
    "compute_line_total",
    "create_transaction",
    "create_user",
    "get_product",
    "list_active_products",
    "list_open_credits",
    "record_payment",
    "seed_users",
    "verify_pin",
]
