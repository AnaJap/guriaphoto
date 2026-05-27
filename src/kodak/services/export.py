"""Export range history (summary + raw transactions) to a single-sheet .xlsx."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from kodak import clock
from kodak.models.enums import CreditStatus, ProductCategory
from kodak.services.history import RangeSummary, TxnDetail

_CAT_LABEL: dict[ProductCategory, str] = {
    ProductCategory.photo:       "ფოტო",
    ProductCategory.enlargement: "გადიდება",
    ProductCategory.frame:       "ჩარჩო",
    ProductCategory.lamination:  "ლამინირება",
    ProductCategory.cd:          "CD",
    ProductCategory.photocopy:   "ქსეროქსი",
    ProductCategory.album:       "ალბომი",
    ProductCategory.other:       "სხვა",
}

_CREDIT_STATUS_LABEL: dict[CreditStatus, str] = {
    CreditStatus.active:   "გახსნილი",
    CreditStatus.cleared:  "დახურული",
    CreditStatus.forgiven: "ნაპატიები",
}

# ── styling tokens ────────────────────────────────────────────────────────
_ACCENT = "FF2E7D32"          # brand green
_ACCENT_SOFT = "FFE6F0E7"     # light green fill
_HEADER_TXT = "FFFFFFFF"
_BORDER_CLR = "FFD9D2C7"
_MONEY_FMT = '#,##0.00 ₾'

_TITLE_FONT   = Font(size=16, bold=True, color=_ACCENT)
_SECTION_FONT = Font(size=12, bold=True, color=_ACCENT)
_LABEL_FONT   = Font(size=11)
_VALUE_FONT   = Font(size=11, bold=True)
_HEAD_FONT    = Font(size=11, bold=True, color=_HEADER_TXT)

_HEAD_FILL    = PatternFill("solid", fgColor=_ACCENT)
_SOFT_FILL    = PatternFill("solid", fgColor=_ACCENT_SOFT)

_THIN = Side(style="thin", color=_BORDER_CLR)
_CELL_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)
_RIGHT = Alignment(horizontal="right", vertical="center")
_WRAP = Alignment(horizontal="left", vertical="center", wrap_text=True)


# Transaction column layout: (header, width, alignment)
_TXN_COLUMNS: list[tuple[str, int, Alignment]] = [
    ("თარიღი",     12, _LEFT),
    ("დრო",         8, _LEFT),
    ("გვარი",      18, _LEFT),
    ("პროდუქტები", 46, _WRAP),
    ("ჯამი",       12, _RIGHT),
    ("გადახდილი",  12, _RIGHT),
    ("ნისია",      12, _RIGHT),
    ("სტატუსი",    12, _LEFT),
    ("შენიშვნა",   28, _WRAP),
]


def export_history_to_xlsx(
    path: Path,
    *,
    start: dt.date,
    end: dt.date,
    summary: RangeSummary,
    rows: list[TxnDetail],
) -> Path:
    """Write a single-sheet workbook: summary metrics on top, raw txns below.

    Returns the written path. Raises on I/O failure (caller handles feedback).
    """
    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "ისტორია"
    ws.sheet_view.showGridLines = False

    _apply_column_widths(ws)

    row = _write_summary_block(ws, start, end, summary)
    row += 1  # spacer row
    _write_transactions_block(ws, rows, start_row=row)

    ws.freeze_panes = None
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


# ── summary ────────────────────────────────────────────────────────────────

def _write_summary_block(
    ws: Worksheet, start: dt.date, end: dt.date, s: RangeSummary
) -> int:
    """Write the header + metric block. Returns the next free row index."""
    r = 1
    cell = ws.cell(row=r, column=1, value="გაყიდვების ისტორია — ანგარიში")
    cell.font = _TITLE_FONT
    r += 1

    period = (
        f"{start:%d.%m.%Y}"
        if start == end
        else f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"
    )
    _kv(ws, r, "პერიოდი:", period)
    r += 1
    _kv(ws, r, "შექმნის თარიღი:", f"{clock.now():%d.%m.%Y %H:%M}")
    r += 2

    ws.cell(row=r, column=1, value="შემაჯამებელი მაჩვენებლები").font = _SECTION_FONT
    r += 1

    metrics: list[tuple[str, object, bool]] = [
        ("სულ გაყიდვები",         s.total_txns,              False),
        ("ჯამური გაყიდვები",      s.total_revenue,           True),
        ("მიღებული გაყიდვებიდან", s.received_from_sales,     True),
        ("დაბრუნებული ნისიები",   s.credit_received_amount,  True),
        ("ახალი ნისიები",         s.new_credit_count,        False),
        ("სალაროში მიღებული",     s.cashier_received,        True),
    ]
    for label, value, is_money in metrics:
        _metric_row(ws, r, label, value, money=is_money)
        r += 1

    # Category breakdown (part of the on-screen summary).
    if s.categories:
        r += 1
        ws.cell(row=r, column=1, value="კატეგორიები").font = _SECTION_FONT
        r += 1
        for col, head in enumerate(("კატეგორია", "რაოდენობა", "შემოსავალი"), start=1):
            c = ws.cell(row=r, column=col, value=head)
            c.font = _HEAD_FONT
            c.fill = _HEAD_FILL
            c.border = _CELL_BORDER
            c.alignment = _LEFT if col == 1 else _RIGHT
        r += 1
        for cs in s.categories:
            name = _CAT_LABEL.get(cs.category, cs.category.value)
            ws.cell(row=r, column=1, value=name).border = _CELL_BORDER
            qc = ws.cell(row=r, column=2, value=cs.qty)
            qc.border = _CELL_BORDER
            qc.alignment = _RIGHT
            rc = ws.cell(row=r, column=3, value=_money(cs.revenue))
            rc.number_format = _MONEY_FMT
            rc.border = _CELL_BORDER
            rc.alignment = _RIGHT
            r += 1

    return r


def _kv(ws: Worksheet, r: int, label: str, value: str) -> None:
    a = ws.cell(row=r, column=1, value=label)
    a.font = _LABEL_FONT
    b = ws.cell(row=r, column=2, value=value)
    b.font = _VALUE_FONT


def _metric_row(ws: Worksheet, r: int, label: str, value, *, money: bool) -> None:
    a = ws.cell(row=r, column=1, value=label)
    a.font = _LABEL_FONT
    a.fill = _SOFT_FILL
    a.border = _CELL_BORDER
    a.alignment = _LEFT
    b = ws.cell(row=r, column=2, value=_money(value) if money else value)
    b.font = _VALUE_FONT
    b.fill = _SOFT_FILL
    b.border = _CELL_BORDER
    b.alignment = _RIGHT
    if money:
        b.number_format = _MONEY_FMT


# ── transactions ─────────────────────────────────────────────────────────

def _write_transactions_block(
    ws: Worksheet, rows: list[TxnDetail], *, start_row: int
) -> int:
    r = start_row
    ws.cell(row=r, column=1, value="ტრანზაქციები").font = _SECTION_FONT
    r += 1

    header_row = r
    for col, (head, _width, _align) in enumerate(_TXN_COLUMNS, start=1):
        c = ws.cell(row=header_row, column=col, value=head)
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.border = _CELL_BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
    r += 1

    if not rows:
        ws.cell(row=r, column=1, value="ამ პერიოდში ჩანაწერი არ არის.").font = _LABEL_FONT
        return r + 1

    # Newest first, matching the on-screen list.
    ordered = sorted(rows, key=lambda d: (d.txn.date, d.txn.created_at), reverse=True)
    for d in ordered:
        _write_txn_row(ws, r, d)
        r += 1

    return r


def _write_txn_row(ws: Worksheet, r: int, d: TxnDetail) -> None:
    products = "; ".join(
        f"{prod.name} {prod.size_label or ''}".strip() + f" ×{li.quantity}"
        for li, prod in d.items
    )

    if d.credit is not None:
        credit_remaining = _money(d.credit.remaining_amount)
        credit_status = _CREDIT_STATUS_LABEL.get(d.credit.status, d.credit.status.value)
    else:
        credit_remaining = None
        credit_status = "—"

    values = [
        f"{d.txn.date:%d.%m.%Y}",
        clock.to_local(d.txn.created_at).strftime("%H:%M"),
        d.txn.customer_surname,
        products or "—",
        _money(d.total),
        _money(d.txn.amount_received),
        credit_remaining,
        credit_status,
        d.txn.notes or "",
    ]
    for col, ((_head, _width, align), value) in enumerate(zip(_TXN_COLUMNS, values), start=1):
        c = ws.cell(row=r, column=col, value=value)
        c.border = _CELL_BORDER
        c.alignment = align
        c.font = _LABEL_FONT
        # Money columns: ჯამი, გადახდილი, ნისია → indexes 5,6,7
        if col in (5, 6, 7) and value is not None:
            c.number_format = _MONEY_FMT


# ── helpers ──────────────────────────────────────────────────────────────

def _apply_column_widths(ws: Worksheet) -> None:
    for col, (_head, width, _align) in enumerate(_TXN_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _money(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return 0.0
    return float(value)
