"""Report tab — period summary with CSV export."""

from __future__ import annotations

import csv
import datetime as dt
import io
import platform
import subprocess
from decimal import Decimal
from pathlib import Path

import flet as ft

from kodak.db import get_session
from kodak.models.enums import ProductCategory
from kodak.models.user import User
from kodak.services.report import ReportData, build_report, last_day_of_month
from kodak.ui.geo import fmt_date, fmt_month_year, fmt_short_date, picker_date
from kodak.ui.theme import (
    ACCENT_GOLD,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)

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

_PRESETS = [
    ("month",      "ეს თვე"),
    ("last_month", "გასული თვე"),
    ("custom",     "↕ პერიოდი"),
]


class ReportView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page     = page
        self._user     = user
        self._mounted  = False
        self._data: ReportData | None = None

        today = dt.date.today()
        self._active_preset = "month"
        self._month = today.replace(day=1)          # first day of displayed month
        self._start = self._month
        self._end   = today

        # ── date pickers ───────────────────────────────────────────
        self._dp_start = ft.DatePicker(
            value=self._start,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დაწყება",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_start_picked,
        )
        self._dp_end = ft.DatePicker(
            value=self._end,
            first_date=dt.date(2020, 1, 1),
            last_date=today,
            help_text="დასრულება",
            confirm_text="კარგი",
            cancel_text="გაუქმება",
            on_change=self._on_end_picked,
        )
        self._page.overlay.extend([self._dp_start, self._dp_end])
        self._page.update()

        # ── mutable controls ───────────────────────────────────────
        self._preset_row   = ft.Row(spacing=SPACE_XS, wrap=True)
        self._period_ctrl  = ft.Container()   # month nav OR date pickers
        self._summary_row  = ft.Row(spacing=SPACE_SM, wrap=True)
        self._cat_col      = ft.Column(spacing=3, tight=True)
        self._day_col      = ft.Column(spacing=2)
        self._export_label = ft.Text("", size=12, color=ft.Colors.PRIMARY)

        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()

    # ── public ────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        export_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=16,
                            color=ft.Colors.WHITE),
                    ft.Text("CSV", size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=ft.Colors.PRIMARY,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=self._export_csv,
            ink=True,
            tooltip="CSV ფაილად შენახვა",
        )

        self._root = ft.Column(
            controls=[
                # Title row
                ft.Row(
                    controls=[
                        ft.Text("ანგარიში", size=28, weight=ft.FontWeight.W_700,
                                expand=True),
                        export_btn,
                        self._export_label,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=SPACE_SM),
                # Preset chips
                self._preset_row,
                # Month nav or date pickers
                self._period_ctrl,
                ft.Container(height=SPACE_XS),
                # Summary cards
                self._summary_row,
                ft.Container(height=SPACE_XS),
                # Category breakdown
                ft.Text("კატეგორიები", size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                self._cat_col,
                ft.Divider(height=SPACE_MD),
                # Per-day table
                ft.Text("დღეების მიხედვით", size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(
                    content=self._day_col,
                    expand=True,
                ),
            ],
            spacing=SPACE_SM,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self._mounted = True
        return self._root

    # ── presets ───────────────────────────────────────────────────

    def _set_preset(self, preset: str) -> None:
        today = dt.date.today()
        if preset == "month":
            self._month = today.replace(day=1)
            self._start = self._month
            self._end   = today
        elif preset == "last_month":
            first_this  = today.replace(day=1)
            last_prev   = first_this - dt.timedelta(days=1)
            self._month = last_prev.replace(day=1)
            self._start = self._month
            self._end   = last_prev
        # "custom" keeps current start/end
        self._active_preset = preset
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    def _rebuild_preset_row(self) -> None:
        chips = []
        for key, label in _PRESETS:
            active = self._active_preset == key

            def on_click(e, k=key):
                self._set_preset(k)

            chips.append(ft.Container(
                content=ft.Text(
                    label, size=12, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_PRIMARY if active else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER,
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
                on_click=on_click,
                ink=not active,
            ))
        self._preset_row.controls = chips

    # ── period control (month nav or date pickers) ────────────────

    def _rebuild_period_ctrl(self) -> None:
        if self._active_preset != "custom":
            self._period_ctrl.content = self._build_month_nav()
        else:
            self._period_ctrl.content = self._build_date_pickers()

    def _build_month_nav(self) -> ft.Control:
        future = last_day_of_month(self._month) >= dt.date.today()

        def prev_month(e):
            # go back one month
            if self._month.month == 1:
                self._month = self._month.replace(year=self._month.year - 1, month=12)
            else:
                self._month = self._month.replace(month=self._month.month - 1)
            self._start = self._month
            self._end   = min(last_day_of_month(self._month), dt.date.today())
            self._rebuild_period_ctrl()
            self._load_data()
            self._flush_ui()

        def next_month(e):
            if future:
                return
            if self._month.month == 12:
                self._month = self._month.replace(year=self._month.year + 1, month=1)
            else:
                self._month = self._month.replace(month=self._month.month + 1)
            self._start = self._month
            self._end   = min(last_day_of_month(self._month), dt.date.today())
            self._rebuild_period_ctrl()
            self._load_data()
            self._flush_ui()

        return ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.CHEVRON_LEFT, size=22),
                    on_click=prev_month,
                    ink=True, border_radius=RADIUS_SM,
                    padding=ft.padding.all(SPACE_XS),
                ),
                ft.Text(
                    fmt_month_year(self._month),
                    size=16, weight=ft.FontWeight.W_700,
                    expand=True, text_align=ft.TextAlign.CENTER,
                ),
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.CHEVRON_RIGHT, size=22,
                        color=ft.Colors.ON_SURFACE_VARIANT if future else None,
                    ),
                    on_click=next_month,
                    ink=not future,
                    border_radius=RADIUS_SM,
                    padding=ft.padding.all(SPACE_XS),
                    opacity=0.35 if future else 1.0,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _build_date_pickers(self) -> ft.Control:
        from_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=ft.Colors.PRIMARY),
                    ft.Text(fmt_short_date(self._start), size=13,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("start"),
            ink=True,
        )
        to_btn = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14,
                            color=ft.Colors.PRIMARY),
                    ft.Text(fmt_short_date(self._end), size=13,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=lambda e: self._open_picker("end"),
            ink=True,
        )
        return ft.Row(
            controls=[
                from_btn,
                ft.Text("–", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                to_btn,
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_picker(self, which: str) -> None:
        if which == "start":
            self._dp_start.value = self._start
            self._dp_start.open  = True
            self._dp_start.update()
        else:
            self._dp_end.value = self._end
            self._dp_end.open  = True
            self._dp_end.update()

    def _on_start_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._start = min(picker_date(raw), dt.date.today())
        if self._start > self._end:
            self._end = self._start
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    def _on_end_picked(self, e) -> None:
        raw = e.control.value
        if raw is None:
            return
        self._end = min(picker_date(raw), dt.date.today())
        if self._end < self._start:
            self._start = self._end
        self._rebuild_period_ctrl()
        self._load_data()
        self._flush_ui()

    # ── data ──────────────────────────────────────────────────────

    def _load_data(self) -> None:
        with get_session() as session:
            self._data = build_report(session, self._start, self._end)
        self._build_summary_controls()
        self._build_cat_controls()
        self._build_day_controls()

    def _build_summary_controls(self) -> None:
        d = self._data
        self._summary_row.controls = [
            _scard("გაყიდვები",  str(d.summary.total_txns),
                   ft.Icons.RECEIPT_LONG,      ACCENT_GOLD),
            _scard("შემოსავალი", f"\u20be{d.summary.total_revenue:.2f}",
                   ft.Icons.PAYMENTS,          ACCENT_GOLD),
            _scard("გატანა",     f"\u20be{d.total_withdrawn:.2f}",
                   ft.Icons.OUTPUT,            ft.Colors.ERROR),
            _scard("სალაროში",   f"\u20be{d.net_cash:.2f}",
                   ft.Icons.ACCOUNT_BALANCE,   ft.Colors.PRIMARY),
            _scard("ნისია",      str(d.summary.open_credit_count),
                   ft.Icons.ACCOUNT_BALANCE_WALLET, ft.Colors.ON_SURFACE_VARIANT),
        ]

    def _build_cat_controls(self) -> None:
        cats = self._data.summary.categories
        if not cats:
            self._cat_col.controls = [
                ft.Text("მონაცემი არ არის", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT)
            ]
            return
        max_rev = max(c.revenue for c in cats) or Decimal("1")
        rows: list[ft.Control] = []
        for cs in cats:
            frac = float(cs.revenue / max_rev)
            rows.append(ft.Row(
                controls=[
                    ft.Text(_CAT_LABEL.get(cs.category, cs.category.value),
                            size=12, width=90,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Stack(
                        controls=[
                            ft.Container(width=160, height=8,
                                         bgcolor=ft.Colors.SURFACE_CONTAINER,
                                         border_radius=4),
                            ft.Container(width=max(4, int(160 * frac)), height=8,
                                         bgcolor=ACCENT_GOLD, border_radius=4),
                        ],
                        width=160, height=8,
                    ),
                    ft.Text(str(cs.qty), size=12, width=32,
                            text_align=ft.TextAlign.RIGHT,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"\u20be{cs.revenue:.2f}", size=12,
                            weight=ft.FontWeight.W_600, width=72,
                            text_align=ft.TextAlign.RIGHT),
                ],
                spacing=SPACE_SM,
            ))
        self._cat_col.controls = rows

    def _build_day_controls(self) -> None:
        days = self._data.days
        if not days:
            self._day_col.controls = [
                ft.Text("ამ პერიოდში ჩანაწერი არ არის", size=13,
                        color=ft.Colors.ON_SURFACE_VARIANT)
            ]
            return

        # header row
        hdr = ft.Row(
            controls=[
                ft.Text("თარიღი",    size=11, width=130,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        weight=ft.FontWeight.W_600),
                ft.Text("გაყ.",      size=11, width=36,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_600),
                ft.Text("შემოსავ.", size=11, width=80,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_600),
                ft.Text("გატანა",   size=11, width=72,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_600),
                ft.Text("სალარო",  size=11, width=72,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_600),
            ],
            spacing=SPACE_SM,
        )

        rows: list[ft.Control] = [hdr, ft.Divider(height=1)]
        for ds in days:
            net_color = ft.Colors.ERROR if ds.net < 0 else None
            rows.append(ft.Row(
                controls=[
                    ft.Text(fmt_date(ds.date), size=12, width=130,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(str(ds.txn_count), size=12, width=36,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(f"\u20be{ds.revenue:.2f}", size=12,
                            weight=ft.FontWeight.W_600, width=80,
                            text_align=ft.TextAlign.RIGHT),
                    ft.Text(
                        f"\u20be{ds.withdrawn:.2f}" if ds.withdrawn else "—",
                        size=12, width=72,
                        text_align=ft.TextAlign.RIGHT,
                        color=ft.Colors.ERROR if ds.withdrawn else ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    ft.Text(f"\u20be{ds.net:.2f}", size=12,
                            weight=ft.FontWeight.W_600, width=72,
                            text_align=ft.TextAlign.RIGHT,
                            color=net_color),
                ],
                spacing=SPACE_SM,
            ))
        self._day_col.controls = rows

    # ── export ────────────────────────────────────────────────────

    def _export_csv(self, e) -> None:
        if self._data is None:
            return
        d = self._data

        buf = io.StringIO()
        w   = csv.writer(buf)

        w.writerow(["ანგარიში"])
        w.writerow([f"{fmt_short_date(d.start)} – {fmt_short_date(d.end)}"])
        w.writerow([])

        w.writerow(["შეჯამება"])
        w.writerow(["გაყიდვები",  d.summary.total_txns])
        w.writerow(["შემოსავალი", f"{d.summary.total_revenue:.2f}"])
        w.writerow(["გატანა",     f"{d.total_withdrawn:.2f}"])
        w.writerow(["სალაროში",   f"{d.net_cash:.2f}"])
        w.writerow(["ღია ნისიები", d.summary.open_credit_count])
        w.writerow(["ნისია (ჯამი)", f"{d.summary.open_credit_amount:.2f}"])
        w.writerow([])

        w.writerow(["კატეგორიები"])
        w.writerow(["კატეგორია", "რაოდ.", "შემოსავალი"])
        for cs in d.summary.categories:
            w.writerow([
                _CAT_LABEL.get(cs.category, cs.category.value),
                cs.qty,
                f"{cs.revenue:.2f}",
            ])
        w.writerow([])

        w.writerow(["დღეების მიხედვით"])
        w.writerow(["თარიღი", "გაყ.", "შემოსავ.", "გატანა", "სალარო"])
        for ds in d.days:
            w.writerow([
                fmt_short_date(ds.date),
                ds.txn_count,
                f"{ds.revenue:.2f}",
                f"{ds.withdrawn:.2f}",
                f"{ds.net:.2f}",
            ])

        content  = buf.getvalue()
        filename = f"kodak_{d.start}_{d.end}.csv"
        path     = Path.home() / "Downloads" / filename
        path.write_text(content, encoding="utf-8-sig")

        # open in default app (Numbers / Excel)
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            elif system == "Windows":
                import os
                os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            pass

        self._export_label.value = f"✓  {filename}"
        if self._mounted:
            self._export_label.update()

    # ── UI flush ──────────────────────────────────────────────────

    def _flush_ui(self) -> None:
        if not self._mounted:
            return
        self._preset_row.update()
        self._period_ctrl.update()
        self._summary_row.update()
        self._cat_col.update()
        self._day_col.update()


# ── helpers ───────────────────────────────────────────────────────────────────

def _scard(label: str, value: str, icon: str, icon_color) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Icon(icon, size=18, color=icon_color),
                ft.Text(value, size=20, weight=ft.FontWeight.W_700),
                ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=SPACE_XS, tight=True,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        border_radius=RADIUS_LG,
        padding=ft.padding.all(SPACE_MD + 4),
        width=150,
    )
