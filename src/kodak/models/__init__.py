"""SQLModel schemas for the Kodak app.

Every table class is re-exported here so ``SQLModel.metadata`` sees them
when ``kodak.db.init_db()`` imports this package.
"""

from kodak.models.cash import CashWithdrawal
from kodak.models.price_history import ProductPriceHistory
from kodak.models.credit import Credit, CreditPayment
from kodak.models.enums import CreditStatus, ProductCategory, Role, StockCategory
from kodak.models.product import Product
from kodak.models.setting import Setting
from kodak.models.stock import StockItem, StockMovement
from kodak.models.transaction import LineItem, Transaction
from kodak.models.user import User

__all__ = [
    "CashWithdrawal",
    "ProductPriceHistory",
    "Credit",
    "CreditPayment",
    "CreditStatus",
    "LineItem",
    "Product",
    "ProductCategory",
    "Role",
    "Setting",
    "StockCategory",
    "StockItem",
    "StockMovement",
    "Transaction",
    "User",
]
