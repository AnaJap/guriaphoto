"""ანალიტიკა tab — period analytics, one chart per sub-tab.

Tabs: შემოსავალი (revenue trend), პროდუქტები (top products), ნისია (credit
movement). Flet 0.84 has no chart widgets, so graphs are drawn with themed
Containers (vertical column charts + horizontal bars).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import flet as ft

from kodak import clock
from kodak.db import get_session
from kodak.models.user import User
from kodak.services.dashboard import (
    CreditMovement,
    DashboardData,
    build_credit_movement,
    build_dashboard,
)
from kodak.ui.geo import fmt_short_date, picker_date
from kodak.ui.theme import (
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    get_active_theme_runtime,
)

_PRESETS = [
    ("week", "ეს კვირა"),
    ("month", "ეს თვე"),
    ("last_month", "გასული თვე"),
    ("custom", "↕ პერიოდი"),
]

_TABS = [
    ("revenue", "შემოსავალი", ft.Icons.SHOW_CHART),
    ("products", "პროდუქტები", ft.Icons.BAR_CHART),
    ("credit", "ნისია", ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED),
]

_REPAID_COLOR = "#1F7A5C"   # green — money coming back in


class DashboardView:
    def __init__(self, page: ft.Page, user: User) -> None:
        self._page = page
        self._user = user
        self._mounted = False
        self._tab = "revenue"
        self._root: ft.Column | None = None
        self._content = ft.Container(expand=True)
        self._tab_row = ft.Row(spacing=SPACE_XS, wrap=True)

        self._data: DashboardData | None = None
        self._credit: CreditMovement | None = None

        today = clock.today()
        self._active_preset = "week"
        self._month = today.replace(day=1)
        self._start, self._end = _current_week(today)

        self._dp_start = ft.DatePicker(
            value=self._start, first_date=dt.date(2020, 1, 1), last_date=today,
            help_text="დაწყება", confirm_text="კარგი", cancel_text="გაუქმება",
            on_change=self._on_start_picked,
        )
        self._dp_end = ft.DatePicker(
            value=self._end, first_date=dt.date(2020, 1, 1), last_date=today,
            help_text="დასრულება", confirm_text="კარგი", cancel_text="გაუქმება",
            on_change=self._on_end_picked,
        )
        self._page.overlay.extend([self._dp_start, self._dp_end])
        self._page.update()

        self._preset_row = ft.Row(spacing=SPACE_XS, wrap=True)
        self._period_ctrl = ft.Container()

        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._rebuild_tab_row()
        self._load_data()

    # ── public ────────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        self._content.content = self._render_tab()
        if self._root is None:
            self._root = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=SPACE_MD)
        self._root.controls = [
            ft.Text("ანალიტიკა", size=28, weight=ft.FontWeight.W_700),
            self._section_card(
                "პერიოდი",
                [self._preset_row, self._period_ctrl],
                runtime,
            ),
            self._tab_row,
            self._content,
        ]
        self._mounted = True
        return self._root

    # ── tabs ──────────────────────────────────────────────────────────

    def _rebuild_tab_row(self) -> None:
        self._tab_row.controls = [self._tab_chip(k, label, icon) for k, label, icon in _TABS]

    def _tab_chip(self, key: str, label: str, icon: str) -> ft.Container:
        runtime = get_active_theme_runtime()
        active = self._tab == key

        def on_click(e, k=key):
            if self._tab == k:
                return
            self._tab = k
            self._rebuild_tab_row()
            self._content.content = self._render_tab()
            if self._mounted:
                self._tab_row.update()
                self._content.update()

        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=14,
                            color=ft.Colors.WHITE if active else runtime.muted_text),
                    ft.Text(label, size=13, weight=ft.FontWeight.W_600,
                            color=ft.Colors.WHITE if active else runtime.muted_text),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
            border=ft.border.all(1, runtime.accent if active else _with_alpha(runtime.accent, 0.20)),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=on_click,
            ink=not active,
        )

    def _render_tab(self) -> ft.Control:
        if self._tab == "revenue":
            return self._render_revenue()
        if self._tab == "products":
            return self._render_products()
        return self._render_credit()

    # ── revenue trend ─────────────────────────────────────────────────

    def _render_revenue(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        d = self._data

        summary = ft.Row(
            controls=[
                _summary_card("გაყიდვები", str(d.total_txns), ft.Icons.RECEIPT_LONG, runtime.accent),
                _summary_card("შემოსავალი", f"₾{d.total_revenue:.2f}", ft.Icons.PAYMENTS, runtime.accent),
                _summary_card("საშ. ჩეკი", f"₾{d.avg_ticket:.2f}", ft.Icons.SHOPPING_BAG_OUTLINED, ft.Colors.PRIMARY),
                _summary_card("აქტიური დღეები", str(d.active_days), ft.Icons.CALENDAR_VIEW_WEEK_OUTLINED, runtime.muted_text),
            ],
            spacing=SPACE_SM, wrap=True,
        )

        if not any(p.revenue > 0 for p in d.daily):
            chart: ft.Control = _empty_state("ამ პერიოდში შემოსავალი არ არის.")
        else:
            buckets = [(_short_day(p.date), [p.revenue]) for p in d.daily]
            chart = _column_chart(buckets, [("შემოსავალი", runtime.accent)])

        return ft.Column(
            controls=[
                summary,
                self._section_card("შემოსავლის დინამიკა (დღეების მიხედვით)", [chart], runtime),
            ],
            spacing=SPACE_MD, tight=True,
        )

    # ── top products ──────────────────────────────────────────────────

    def _render_products(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        assert self._data is not None
        items = self._data.top_products
        if not items:
            body: list[ft.Control] = [_empty_state("ამ პერიოდში გაყიდვები არ არის.")]
        else:
            max_rev = max((it.revenue for it in items), default=Decimal("1")) or Decimal("1")
            body = [
                _metric_bar_row(
                    label=it.label,
                    primary=f"₾{it.revenue:.2f}",
                    secondary=f"{it.qty} ც",
                    fraction=float(it.revenue / max_rev),
                    color=runtime.accent,
                )
                for it in items
            ]
        return self._section_card("ტოპ პროდუქტები (შემოსავლით)", body, runtime)

    # ── credit movement ───────────────────────────────────────────────

    def _render_credit(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        assert self._credit is not None
        c = self._credit

        cards = ft.Row(
            controls=[
                _summary_card("ახალი ნისია", f"₾{c.issued_amount:.2f}",
                              ft.Icons.POST_ADD, runtime.accent, note=f"{c.issued_count} ცალი"),
                _summary_card("დაბრუნებული", f"₾{c.repaid_amount:.2f}",
                              ft.Icons.REPLAY_CIRCLE_FILLED_OUTLINED, _REPAID_COLOR,
                              note=f"{c.repaid_count} გადახდა"),
                _summary_card("ნაპატიები", f"₾{c.forgiven_amount:.2f}",
                              ft.Icons.MONEY_OFF, "#9575CD", note=f"{c.forgiven_count} ცალი"),
                _summary_card("მიმდინარე ნაშთი", f"₾{c.outstanding_now:.2f}",
                              ft.Icons.ACCOUNT_BALANCE_WALLET, ft.Colors.ERROR,
                              note="გადაუხდელი ჯამში"),
            ],
            spacing=SPACE_SM, wrap=True,
        )

        if not any(p.issued > 0 or p.repaid > 0 for p in c.daily):
            chart: ft.Control = _empty_state("ამ პერიოდში ნისიის მოძრაობა არ ყოფილა.")
        else:
            buckets = [(_short_day(p.date), [p.issued, p.repaid]) for p in c.daily]
            chart = ft.Column(
                controls=[
                    _legend([("გაცემული", runtime.accent), ("დაბრუნებული", _REPAID_COLOR)]),
                    _column_chart(buckets, [("გაცემული", runtime.accent),
                                            ("დაბრუნებული", _REPAID_COLOR)]),
                ],
                spacing=SPACE_SM, tight=True,
            )

        return ft.Column(
            controls=[
                cards,
                self._section_card("ნისიის მოძრაობა (დღეების მიხედვით)", [chart], runtime),
            ],
            spacing=SPACE_MD, tight=True,
        )

    # ── period control ────────────────────────────────────────────────

    def _set_preset(self, preset: str) -> None:
        today = clock.today()
        if preset == "week":
            self._start, self._end = _current_week(today)
        elif preset == "month":
            self._month = today.replace(day=1)
            self._start, self._end = self._month, today
        elif preset == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - dt.timedelta(days=1)
            self._month = last_prev.replace(day=1)
            self._start, self._end = self._month, last_prev
        self._active_preset = preset
        self._on_period_changed()

    def _rebuild_preset_row(self) -> None:
        runtime = get_active_theme_runtime()
        chips = []
        for key, label in _PRESETS:
            active = self._active_preset == key

            def on_click(e, preset_id=key):
                self._set_preset(preset_id)

            chips.append(ft.Container(
                content=ft.Text(label, size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.WHITE if active else runtime.muted_text),
                bgcolor=runtime.accent if active else _with_alpha(runtime.accent, 0.08),
                border=ft.border.all(1, runtime.accent if active else _with_alpha(runtime.accent, 0.18)),
                border_radius=RADIUS_SM,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=5),
                on_click=on_click, ink=not active,
            ))
        self._preset_row.controls = chips

    def _rebuild_period_ctrl(self) -> None:
        self._period_ctrl.content = (
            self._build_date_pickers() if self._active_preset == "custom"
            else self._build_period_label()
        )

    def _build_period_label(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CALENDAR_MONTH_OUTLINED, size=16, color=runtime.accent),
                    ft.Text(f"{fmt_short_date(self._start)} – {fmt_short_date(self._end)}",
                            size=13, weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_XS, tight=True,
            ),
            bgcolor=runtime.panel_bg, border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
        )

    def _build_date_pickers(self) -> ft.Control:
        runtime = get_active_theme_runtime()

        def pill(text, which):
            return ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=14, color=runtime.accent),
                        ft.Text(text, size=13, weight=ft.FontWeight.W_600),
                    ],
                    spacing=SPACE_XS, tight=True,
                ),
                bgcolor=runtime.panel_bg, border=ft.border.all(1, runtime.panel_border),
                border_radius=RADIUS_MD,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
                on_click=lambda e: self._open_picker(which), ink=True,
            )

        return ft.Row(
            controls=[
                pill(fmt_short_date(self._start), "start"),
                ft.Text("–", size=16, color=runtime.muted_text),
                pill(fmt_short_date(self._end), "end"),
            ],
            spacing=SPACE_SM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_picker(self, which: str) -> None:
        dp = self._dp_start if which == "start" else self._dp_end
        dp.value = self._start if which == "start" else self._end
        dp.open = True
        dp.update()

    def _on_start_picked(self, e) -> None:
        if e.control.value is None:
            return
        self._active_preset = "custom"
        self._start = min(picker_date(e.control.value), clock.today())
        if self._start > self._end:
            self._end = self._start
        self._on_period_changed()

    def _on_end_picked(self, e) -> None:
        if e.control.value is None:
            return
        self._active_preset = "custom"
        self._end = min(picker_date(e.control.value), clock.today())
        if self._end < self._start:
            self._start = self._end
        self._on_period_changed()

    def _on_period_changed(self) -> None:
        self._rebuild_preset_row()
        self._rebuild_period_ctrl()
        self._load_data()
        self._content.content = self._render_tab()
        if self._mounted:
            self._preset_row.update()
            self._period_ctrl.update()
            self._content.update()

    # ── data ──────────────────────────────────────────────────────────

    def _load_data(self) -> None:
        with get_session() as session:
            self._data = build_dashboard(session, self._start, self._end)
            self._credit = build_credit_movement(session, self._start, self._end)

    # ── shared ────────────────────────────────────────────────────────

    def _section_card(self, title: str, controls: list[ft.Control], runtime) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[ft.Text(title, size=16, weight=ft.FontWeight.W_700), *controls],
                spacing=SPACE_SM, tight=True,
            ),
            bgcolor=runtime.panel_bg, border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG, padding=ft.padding.all(SPACE_LG),
        )


# ── helpers ─────────────────────────────────────────────────────────────────

def _current_week(today: dt.date) -> tuple[dt.date, dt.date]:
    return today - dt.timedelta(days=today.weekday()), today


def _short_day(d: dt.date) -> str:
    return f"{d.day:02d}/{d.month:02d}"


def _column_chart(
    buckets: list[tuple[str, list]],
    series: list[tuple[str, str]],
    *,
    height: int = 150,
    bar_w: int = 12,
) -> ft.Control:
    """Vertical column chart. `buckets` = [(label, [values per series])]."""
    max_v = max(
        (float(v) for _, vals in buckets for v in vals),
        default=0.0,
    ) or 1.0
    cell_w = max(bar_w * len(series) + 2 * (len(series) - 1), 22)

    cells: list[ft.Control] = []
    for label, vals in buckets:
        bars = []
        for (name, color), v in zip(series, vals):
            bars.append(ft.Container(
                width=bar_w,
                height=max(2, int(float(v) / max_v * height)),
                bgcolor=color,
                border_radius=3,
                tooltip=f"{label} · {name}: ₾{float(v):.2f}",
            ))
        cells.append(ft.Column(
            controls=[
                ft.Container(
                    content=ft.Row(bars, spacing=2,
                                   vertical_alignment=ft.CrossAxisAlignment.END, tight=True),
                    height=height,
                    alignment=ft.Alignment(0, 1),
                ),
                ft.Text(label, size=8, color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER, width=cell_w),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ))

    return ft.Row(
        controls=cells,
        spacing=SPACE_SM,
        vertical_alignment=ft.CrossAxisAlignment.START,
        scroll=ft.ScrollMode.AUTO,
    )


def _legend(items: list[tuple[str, str]]) -> ft.Control:
    runtime = get_active_theme_runtime()
    chips = []
    for name, color in items:
        chips.append(ft.Row(
            controls=[
                ft.Container(width=12, height=12, bgcolor=color, border_radius=3),
                ft.Text(name, size=11, color=runtime.muted_text),
            ],
            spacing=SPACE_XS, tight=True,
        ))
    return ft.Row(chips, spacing=SPACE_MD, wrap=True)


def _summary_card(label: str, value: str, icon: str, color: str,
                  *, note: str | None = None) -> ft.Control:
    runtime = get_active_theme_runtime()
    text_controls: list[ft.Control] = [
        ft.Text(value, size=20, weight=ft.FontWeight.W_700),
        ft.Text(label, size=12, color=runtime.muted_text),
    ]
    if note:
        text_controls.append(ft.Text(note, size=10, color=runtime.muted_text))
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(icon, size=18, color=color),
                    bgcolor=_with_alpha(color, 0.10),
                    border_radius=12,
                    padding=ft.padding.all(SPACE_SM),
                ),
                ft.Column(controls=text_controls, spacing=2, tight=True),
            ],
            spacing=SPACE_SM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=runtime.panel_bg, border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_LG, padding=ft.padding.all(SPACE_MD), width=196,
    )


def _metric_bar_row(*, label: str, primary: str, secondary: str,
                    fraction: float, color: str) -> ft.Control:
    runtime = get_active_theme_runtime()
    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(primary, size=12, weight=ft.FontWeight.W_700),
                    ft.Text(secondary, size=11, color=runtime.muted_text),
                ],
                spacing=SPACE_SM,
            ),
            ft.Stack(
                controls=[
                    ft.Container(height=10, bgcolor=_with_alpha(color, 0.10), border_radius=5),
                    ft.Container(
                        width=max(10, int(260 * max(0.0, min(1.0, fraction)))),
                        height=10, bgcolor=color, border_radius=5,
                    ),
                ],
                width=260, height=10,
            ),
        ],
        spacing=SPACE_XS, tight=True,
    )


def _empty_state(message: str) -> ft.Control:
    return ft.Text(message, size=12, color=get_active_theme_runtime().muted_text)


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
