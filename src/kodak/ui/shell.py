"""App shell — collapsible sidebar + swappable content area."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from kodak.access import AccessMode
from kodak.session_lock import SessionLockInfo, describe_heartbeat_age
from kodak.models.user import User
from kodak.ui.credits_view import CreditsView
from kodak.ui.dashboard_view import DashboardView
from kodak.ui.products_view import ProductsView
from kodak.ui.settings_view import SettingsView
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
from kodak.ui.today_view import TodayView

_NAV = [
    ("ჟურნალი",     ft.Icons.TODAY_OUTLINED,                  ft.Icons.TODAY),
    ("ნისია",       ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, ft.Icons.ACCOUNT_BALANCE_WALLET),
    ("პროდუქტები",  ft.Icons.PHOTO_CAMERA_OUTLINED,           ft.Icons.PHOTO_CAMERA),
    ("ანგარიშები",  ft.Icons.BAR_CHART_OUTLINED,              ft.Icons.BAR_CHART),
    ("დეშბორდები",  ft.Icons.DASHBOARD_OUTLINED,              ft.Icons.DASHBOARD),
    ("პარამეტრები", ft.Icons.SETTINGS_OUTLINED,               ft.Icons.SETTINGS),
]

_W_EXPANDED  = 204
_W_COLLAPSED = 60


class AppShell:
    def __init__(
        self,
        page: ft.Page,
        user: User,
        on_logout: Callable[[], None],
        *,
        on_request_close: Callable[[], None] | None = None,
        access_mode: AccessMode = AccessMode.edit,
        editor_lock: SessionLockInfo | None = None,
    ) -> None:
        self._page      = page
        self._user      = user
        self._on_logout = on_logout
        self._on_request_close = on_request_close
        self._access_mode = access_mode
        self._editor_lock = editor_lock
        self._selected  = 0
        self._collapsed = False

        # Views that add controls to page.overlay are cached so those
        # controls are not duplicated on every navigation visit.
        self._today_view:  TodayView | None  = None
        self._credits_view: CreditsView | None = None
        self._products_view: ProductsView | None = None
        self._report_view: "ReportView | None" = None  # type: ignore[name-defined]
        self._dashboard_view: DashboardView | None = None
        self._settings_view: SettingsView | None = None

        self._content_area = ft.Container(
            expand=True,
            padding=ft.padding.all(SPACE_LG + SPACE_MD),
            animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        )
        self._sidebar = ft.Container(
            animate=ft.Animation(220, ft.AnimationCurve.EASE_IN_OUT),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

        self._apply_runtime_chrome()
        self._rebuild_sidebar()
        self._content_area.content = self._get_today_view().build()

    # ── public ──────────────────────────────────────────────────────

    def build(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        return ft.Row(
            controls=[
                self._sidebar,
                ft.VerticalDivider(
                    width=1,
                    thickness=1,
                    color=_with_alpha(runtime.sidebar_fg, 0.12),
                ),
                self._content_area,
            ],
            expand=True,
            spacing=0,
        )

    # ── view cache ──────────────────────────────────────────────────

    def _get_today_view(self) -> TodayView:
        if self._today_view is None:
            self._today_view = TodayView(page=self._page, user=self._user)
        return self._today_view

    def _get_credits_view(self) -> CreditsView:
        if self._credits_view is None:
            self._credits_view = CreditsView(page=self._page, user=self._user)
        return self._credits_view

    def _get_products_view(self) -> ProductsView:
        if self._products_view is None:
            self._products_view = ProductsView(page=self._page, user=self._user)
        return self._products_view

    def _get_report_view(self):
        if self._report_view is None:
            from kodak.ui.report_view import ReportView
            self._report_view = ReportView(page=self._page, user=self._user)
        return self._report_view

    def _get_dashboard_view(self) -> DashboardView:
        if self._dashboard_view is None:
            self._dashboard_view = DashboardView(page=self._page, user=self._user)
        return self._dashboard_view

    def _get_settings_view(self) -> SettingsView:
        if self._settings_view is None:
            self._settings_view = SettingsView(
                page=self._page,
                user=self._user,
                on_request_close=self._on_request_close,
                on_theme_preview=self._refresh_theme_chrome,
                access_mode=self._access_mode,
                editor_lock=self._editor_lock,
            )
        return self._settings_view

    # ── sidebar ─────────────────────────────────────────────────────

    def _rebuild_sidebar(self) -> None:
        runtime = get_active_theme_runtime()
        c = self._collapsed
        self._sidebar.width = _W_COLLAPSED if c else _W_EXPANDED

        nav_items = [self._build_nav_item(i) for i in range(len(_NAV))]
        brand = _brand_block(c, runtime)

        toggle = ft.Container(
            content=ft.Icon(
                ft.Icons.CHEVRON_LEFT if not c else ft.Icons.CHEVRON_RIGHT,
                size=18, color=runtime.sidebar_fg,
            ),
            on_click=self._on_toggle,
            ink=True,
            border_radius=RADIUS_SM,
            padding=ft.padding.all(SPACE_SM),
            alignment=ft.Alignment(0, 0),
            tooltip="სვეტის სიგანე",
            margin=ft.margin.only(bottom=SPACE_XS),
        )

        initials = "".join(p[0].upper() for p in self._user.full_name.split()[:2])
        avatar = ft.Container(
            content=ft.Text(initials, size=12,
                            weight=ft.FontWeight.W_700,
                            color=runtime.sidebar_active_fg),
            bgcolor=runtime.sidebar_active_bg,
            width=32, height=32, border_radius=16,
            alignment=ft.Alignment(0, 0),
        )
        logout_btn = ft.Container(
            content=ft.Icon(ft.Icons.LOGOUT, size=16, color=runtime.accent),
            on_click=lambda e: self._on_logout(),
            ink=True, border_radius=RADIUS_SM,
            padding=ft.padding.all(SPACE_XS),
            tooltip="გასვლა",
        )

        if c:
            user_section = ft.Container(
                content=ft.Column(
                    controls=[avatar, logout_btn],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=SPACE_SM, tight=True,
                ),
                padding=ft.padding.symmetric(vertical=SPACE_MD),
                alignment=ft.Alignment(0, 0),
                bgcolor=_with_alpha(runtime.sidebar_fg, 0.08),
                border_radius=RADIUS_MD,
                margin=ft.margin.symmetric(horizontal=SPACE_SM),
            )
        else:
            user_section = ft.Container(
                content=ft.Row(
                    controls=[
                        avatar,
                        ft.Text(self._user.full_name, size=12,
                                weight=ft.FontWeight.W_600, expand=True,
                                overflow=ft.TextOverflow.ELLIPSIS, no_wrap=True,
                                color=runtime.sidebar_fg),
                        logout_btn,
                    ],
                    spacing=SPACE_SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.all(SPACE_MD),
                bgcolor=_with_alpha(runtime.sidebar_fg, 0.08),
                border_radius=RADIUS_MD,
                margin=ft.margin.symmetric(horizontal=SPACE_SM),
            )

        status_section = self._status_block(c, runtime)

        self._sidebar.content = ft.Column(
            controls=[
                ft.Container(height=SPACE_MD),
                brand,
                ft.Container(height=SPACE_SM),
                *nav_items,
                ft.Container(expand=True),
                toggle,
                status_section,
                ft.Divider(height=1, thickness=1, color=_with_alpha(runtime.sidebar_fg, 0.12)),
                user_section,
                ft.Container(height=SPACE_SM),
            ],
            expand=True,
            spacing=2,
        )

    def _build_nav_item(self, index: int) -> ft.Container:
        runtime = get_active_theme_runtime()
        label, icon_off, icon_on = _NAV[index]
        selected = self._selected == index

        def on_click(e, i=index):
            if self._selected == i:
                return
            self._selected = i
            self._rebuild_sidebar()
            self._sidebar.update()
            self._switch_view(i)

        if self._collapsed:
            return ft.Container(
                content=ft.Icon(
                    icon_on if selected else icon_off, size=22,
                    color=runtime.sidebar_active_fg if selected else _with_alpha(runtime.sidebar_fg, 0.86),
                ),
                bgcolor=runtime.sidebar_active_bg if selected else None,
                border_radius=RADIUS_MD,
                width=40, height=40,
                alignment=ft.Alignment(0, 0),
                on_click=on_click,
                ink=not selected,
                tooltip=label,
                margin=ft.margin.symmetric(horizontal=10, vertical=1),
            )
        else:
            return ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon_on if selected else icon_off, size=20,
                                color=runtime.sidebar_active_fg if selected else _with_alpha(runtime.sidebar_fg, 0.86)),
                        ft.Text(label, size=13,
                                weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_400,
                                color=runtime.sidebar_active_fg if selected else _with_alpha(runtime.sidebar_fg, 0.86)),
                    ],
                    spacing=SPACE_SM, tight=True,
                ),
                bgcolor=runtime.sidebar_active_bg if selected else None,
                border_radius=RADIUS_MD,
                padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM + 2),
                margin=ft.margin.symmetric(horizontal=SPACE_SM, vertical=1),
                on_click=on_click,
                ink=not selected,
            )

    def _on_toggle(self, e) -> None:
        self._collapsed = not self._collapsed
        self._rebuild_sidebar()
        self._sidebar.update()

    def _apply_runtime_chrome(self) -> None:
        runtime = get_active_theme_runtime()
        self._sidebar.bgcolor = runtime.sidebar_bg
        self._content_area.bgcolor = runtime.app_bg

    def _refresh_theme_chrome(self) -> None:
        self._apply_runtime_chrome()
        self._rebuild_sidebar()
        self._sidebar.update()
        self._content_area.update()
        self._page.update()

    # ── routing ─────────────────────────────────────────────────────

    def _switch_view(self, index: int) -> None:
        if index == 0:
            self._content_area.content = self._get_today_view().build()
        elif index == 1:
            self._content_area.content = self._get_credits_view().build()
        elif index == 2:
            self._content_area.content = self._get_products_view().build()
        elif index == 3:
            self._content_area.content = self._get_report_view().build()
        elif index == 4:
            self._content_area.content = self._get_dashboard_view().build()
        else:
            self._content_area.content = self._get_settings_view().build()
        self._content_area.update()

    def _status_block(self, collapsed: bool, runtime) -> ft.Control:
        read_only = self._access_mode == AccessMode.read_only
        icon = ft.Icons.VISIBILITY_OUTLINED if read_only else ft.Icons.EDIT_OUTLINED
        label = "მხოლოდ ნახვა" if read_only else "რედაქტირება"
        color = "#D32F2F" if read_only else runtime.accent

        if collapsed:
            return ft.Container(
                content=ft.Icon(icon, size=18, color=color),
                tooltip=label,
                margin=ft.margin.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
                alignment=ft.Alignment(0, 0),
            )

        detail = ""
        if read_only and self._editor_lock is not None:
            who = self._editor_lock.kodak_user or "უცნობი"
            detail = f"{who} @ {self._editor_lock.host}"
        elif read_only:
            detail = "ცვლილებები გამორთულია"
        else:
            detail = "აქტიური სესია"

        controls: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Icon(icon, size=15, color=color),
                    ft.Text(label, size=12, weight=ft.FontWeight.W_700, color=color, expand=True),
                ],
                spacing=SPACE_XS,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                detail,
                size=10,
                color=_with_alpha(runtime.sidebar_fg, 0.72),
                overflow=ft.TextOverflow.ELLIPSIS,
                no_wrap=True,
            ),
        ]
        if read_only and self._editor_lock is not None:
            controls.append(
                ft.Text(
                    f"განახლდა {describe_heartbeat_age(self._editor_lock.heartbeat_at)} წინ",
                    size=10,
                    color=_with_alpha(runtime.sidebar_fg, 0.62),
                    overflow=ft.TextOverflow.ELLIPSIS,
                    no_wrap=True,
                )
            )
        if read_only:
            controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.REFRESH, size=14, color=runtime.sidebar_active_fg),
                            ft.Text(
                                "განახლება",
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=runtime.sidebar_active_fg,
                            ),
                        ],
                        spacing=SPACE_XS,
                        tight=True,
                    ),
                    bgcolor=runtime.sidebar_active_bg,
                    border_radius=RADIUS_SM,
                    padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
                    on_click=self._refresh_current_view,
                    ink=True,
                )
            )

        return ft.Container(
            content=ft.Column(controls=controls, spacing=3, tight=True),
            bgcolor=_with_alpha(color, 0.10),
            border=ft.border.all(1, _with_alpha(color, 0.22)),
            border_radius=RADIUS_MD,
            padding=ft.padding.all(SPACE_SM),
            margin=ft.margin.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
        )

    def _refresh_current_view(self, e=None) -> None:
        self._today_view = None
        self._report_view = None
        self._dashboard_view = None
        self._settings_view = None
        self._switch_view(self._selected)


# ── helpers ─────────────────────────────────────────────────────────────────

def _placeholder(title: str, subtitle: str, icon: str) -> ft.Control:
    runtime = get_active_theme_runtime()
    return ft.Column(
        controls=[
            ft.Text(title, size=28, weight=ft.FontWeight.W_700),
            ft.Container(height=SPACE_LG),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(icon, size=48, color=runtime.muted_text),
                        ft.Text(subtitle, size=14, color=runtime.muted_text),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=SPACE_SM, tight=True,
                ),
                bgcolor=runtime.panel_bg,
                border=ft.border.all(1, runtime.panel_border),
                border_radius=RADIUS_LG,
                padding=ft.padding.all(SPACE_LG * 2),
                alignment=ft.Alignment(0, 0),
            ),
        ],
        spacing=SPACE_XS,
    )


def _brand_block(collapsed: bool, runtime) -> ft.Control:
    badge = ft.Container(
        content=ft.Text(
            "K",
            size=20 if collapsed else 22,
            weight=ft.FontWeight.W_900,
            color=runtime.sidebar_active_fg,
        ),
        bgcolor=runtime.sidebar_active_bg,
        width=38,
        height=38,
        border_radius=12,
        alignment=ft.Alignment(0, 0),
    )

    if collapsed:
        return ft.Container(
            content=badge,
            alignment=ft.Alignment(0, 0),
            margin=ft.margin.symmetric(horizontal=SPACE_SM),
        )

    return ft.Container(
        content=ft.Row(
            controls=[
                badge,
                ft.Column(
                    controls=[
                        ft.Text(
                            "KODAK",
                            size=18,
                            weight=ft.FontWeight.W_900,
                            color=runtime.sidebar_fg,
                        ),
                        ft.Text(
                            "გურიაფოტო სტუდია",
                            size=11,
                            color=_with_alpha(runtime.sidebar_fg, 0.72),
                        ),
                    ],
                    spacing=0,
                    tight=True,
                ),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        margin=ft.margin.symmetric(horizontal=SPACE_SM),
        padding=ft.padding.all(SPACE_SM),
        border_radius=RADIUS_MD,
        bgcolor=_with_alpha(runtime.sidebar_fg, 0.08),
    )


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"
