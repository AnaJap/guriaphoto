"""Shared appearance settings plus admin-only system settings."""

from __future__ import annotations

import os
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import flet as ft

from kodak import clock
from kodak.access import AccessMode
from kodak.backup import (
    BackupError,
    backup_log_path,
    backup_storage_dir,
    clean_backups_between,
    create_manual_backup,
    keep_backups_for_recent_months,
    keep_latest_backups,
    restore_database_from,
    snapshot_database_to,
)
from kodak.config import load_config, save_config
from kodak.db import DB_PATH
from kodak.event_log import EVENT_LOG_PATH, log_event
from kodak.models.enums import Role
from kodak.models.user import User
from kodak.services.export import export_all_to_xlsx
from kodak.session_lock import SessionLockInfo, describe_heartbeat_age, read_session_lock
from kodak.ui.theme import (
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
    THEME_PRESETS,
    ThemeRuntime,
    apply_page_theme,
    default_theme_preference,
    get_active_theme_runtime,
    is_valid_hex_color,
    load_user_theme_preference,
    resolve_theme_runtime,
    save_user_theme_preference,
)


class SettingsView:
    def __init__(
        self,
        page: ft.Page,
        user: User,
        *,
        on_request_close: Callable[[], None] | None = None,
        on_theme_preview: Callable[[], None] | None = None,
        access_mode: AccessMode = AccessMode.edit,
        editor_lock: SessionLockInfo | None = None,
    ) -> None:
        self._page = page
        self._user = user
        self._is_admin = user.role == Role.admin
        self._access_mode = access_mode
        self._editor_lock = editor_lock
        self._can_write = access_mode == AccessMode.edit
        self._on_request_close = on_request_close
        self._on_theme_preview = on_theme_preview

        self._config = load_config()
        self._pending_db_folder: Path | None = None
        self._pending_restore_file: Path | None = None
        self._root: ft.Column | None = None

        self._saved_theme_pref = load_user_theme_preference(user.id)
        self._draft_theme_pref = deepcopy(self._saved_theme_pref)

        self._db_picker = ft.FilePicker()
        self._backup_picker = ft.FilePicker()
        self._restore_picker = ft.FilePicker()
        self._export_picker = ft.FilePicker()
        self._page.services.extend([
            self._db_picker, self._backup_picker, self._restore_picker,
            self._export_picker,
        ])
        self._page.update()

        # Appearance controls
        self._selection_label = ft.Text("", size=12)
        self._theme_feedback = ft.Text("", size=12)
        self._custom_feedback = ft.Text("", size=12)
        self._preset_row = ft.Row(spacing=SPACE_SM, scroll=ft.ScrollMode.AUTO)
        self._preview_card = ft.Container()
        self._custom_theme_visible = self._draft_theme_pref["selection"] == "custom"
        self._custom_theme_toggle = self._action_button(
            "საკუთარი პალიტრა",
            ft.Colors.SURFACE_CONTAINER_HIGH,
            self._on_toggle_custom_theme,
            text_color=ft.Colors.ON_SURFACE,
        )
        self._custom_theme_panel = ft.Container(visible=self._custom_theme_visible)
        self._seed_field = self._make_color_field("ძირითადი ფერი", "seed_color")
        self._accent_field = self._make_color_field("აქცენტი", "accent_color")
        self._app_bg_field = self._make_color_field("ფონი", "app_bg")
        self._sidebar_bg_field = self._make_color_field("გვერდითი სვეტი", "sidebar_bg")

        # System controls
        self._db_path_text = ft.Text("", selectable=True, size=13)
        self._db_folder_text = ft.Text(
            "", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT
        )
        self._db_feedback = ft.Text("", size=12)
        self._pending_db_card = ft.Container(visible=False)

        self._backup_folder_text = ft.Text(
            "", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT
        )
        self._backup_destination_text = ft.Text(
            "", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT
        )
        self._last_manual_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._last_auto_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._backup_log_text = ft.Text("", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._backup_health_text = ft.Text("", size=12)
        self._sync_status_text = ft.Text("", size=12)
        self._event_log_text = ft.Text(
            str(EVENT_LOG_PATH),
            selectable=True,
            size=12,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self._backup_feedback = ft.Text("", size=12)
        self._restore_feedback = ft.Text("", size=12)
        self._export_feedback = ft.Text("", size=12)
        self._cleanup_feedback = ft.Text("", size=12)
        self._cleanup_start_field = ft.TextField(
            label="დაწყება",
            hint_text="YYYY-MM-DD",
            text_size=13,
            border_radius=RADIUS_MD,
            width=160,
        )
        self._cleanup_end_field = ft.TextField(
            label="დასრულება",
            hint_text="YYYY-MM-DD",
            text_size=13,
            border_radius=RADIUS_MD,
            width=160,
        )
        self._keep_count_field = ft.TextField(
            label="ბოლო N ასლი",
            value="30",
            text_size=13,
            border_radius=RADIUS_MD,
            width=140,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._keep_months_field = ft.TextField(
            label="ბოლო N თვე",
            value="6",
            text_size=13,
            border_radius=RADIUS_MD,
            width=140,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._pending_restore_card = ft.Container(visible=False)
        runtime = get_active_theme_runtime()
        self._manual_backup_btn = self._action_button(
            "ახლავე სარეზერვო ასლის შექმნა",
            runtime.accent,
            self._on_manual_backup,
        )

        self._refresh_config_labels()
        self._refresh_theme_controls()

    def build(self) -> ft.Control:
        if self._root is None:
            controls: list[ft.Control] = [
                ft.Text("პარამეტრები", size=28, weight=ft.FontWeight.W_700),
                ft.Text(
                    "აირჩიეთ თქვენთვის სასურველი ვიზუალური თემა. "
                    "ადმინისტრატორი აქვე მართავს სისტემურ პარამეტრებსაც.",
                    size=13,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(height=SPACE_SM),
                self._build_appearance_section(),
                self._build_session_section(),
            ]

            if self._is_admin:
                controls.append(self._build_system_section())

            self._root = ft.Column(
                controls=controls,
                expand=True,
                spacing=SPACE_MD,
                scroll=ft.ScrollMode.AUTO,
            )

        return self._root

    def _build_appearance_section(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        return self._section_card(
            "გარეგნობა",
            [
                ft.Row(
                    controls=[
                        self._selection_label,
                        self._custom_theme_toggle,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
                self._preset_row,
                self._preview_card,
                self._custom_theme_panel,
                ft.Row(
                    controls=[
                        self._action_button("შენახვა", runtime.accent, self._on_save_theme),
                        self._action_button(
                            "გაუქმება",
                            ft.Colors.SURFACE_CONTAINER_HIGH,
                            self._on_cancel_theme,
                            text_color=ft.Colors.ON_SURFACE,
                        ),
                        self._action_button(
                            "ნაგულისხმევზე დაბრუნება",
                            ft.Colors.PRIMARY,
                            self._on_reset_theme,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                ),
                self._theme_feedback,
            ],
        )

    def _build_system_section(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        return self._section_card(
            "სისტემა",
            [
                ft.Text(
                    "ქვემოთ მოცემული მოქმედებები მხოლოდ ადმინისტრატორისთვისაა.",
                    size=12,
                    color=runtime.muted_text,
                ),
                self._build_db_section(),
                self._build_backup_section(),
                self._build_export_section(),
            ],
        )

    def _build_export_section(self) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Divider(height=1),
                ft.Text("მონაცემთა ექსპორტი", size=18, weight=ft.FontWeight.W_700),
                ft.Text(
                    "ყველა მონაცემი (გაყიდვები, ნისია, გადახდები, გატანები, "
                    "პროდუქტები) ერთ Excel ფაილში.",
                    size=12,
                    color=get_active_theme_runtime().muted_text,
                ),
                ft.Row(
                    controls=[
                        self._action_button(
                            "Excel-ში ექსპორტი (ყველა მონაცემი)",
                            get_active_theme_runtime().accent,
                            self._on_pick_export_all,
                        ),
                    ],
                    wrap=True,
                ),
                self._export_feedback,
            ],
            spacing=SPACE_SM,
            tight=True,
        )

    def _build_session_section(self) -> ft.Control:
        runtime = get_active_theme_runtime()
        read_only = self._access_mode == AccessMode.read_only
        status = "მხოლოდ ნახვა" if read_only else "რედაქტირება"
        icon = ft.Icons.VISIBILITY_OUTLINED if read_only else ft.Icons.EDIT_OUTLINED
        color = ft.Colors.ERROR if read_only else runtime.accent

        details: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Icon(icon, size=18, color=color),
                    ft.Text(status, size=14, weight=ft.FontWeight.W_700, color=color),
                ],
                spacing=SPACE_XS,
                tight=True,
            ),
            _label_value("მოვლენების ჟურნალი", self._event_log_text),
            _label_value("სინქრონიზაციის მდგომარეობა", self._sync_status_text),
        ]

        if self._editor_lock is not None:
            editor = self._editor_lock.kodak_user or "უცნობი"
            details.extend(
                [
                    ft.Text(
                        f"რედაქტირებს: {editor} @ {self._editor_lock.host}",
                        size=12,
                        color=runtime.muted_text,
                    ),
                    ft.Text(
                        f"ბოლო heartbeat: {describe_heartbeat_age(self._editor_lock.heartbeat_at)} წინ",
                        size=12,
                        color=runtime.muted_text,
                    ),
                ]
            )
        elif not read_only:
            details.append(ft.Text("ეს კომპიუტერი ფლობს რედაქტირების სესიას.", size=12, color=runtime.muted_text))

        if self._is_admin and self._can_write and self._on_request_close is not None:
            details.append(
                self._action_button(
                    "რედაქტირების გათავისუფლება",
                    ft.Colors.ERROR_CONTAINER,
                    self._on_release_edit_lock,
                    text_color=ft.Colors.ON_ERROR_CONTAINER,
                )
            )
        elif read_only:
            details.append(
                ft.Text(
                    "ცვლილებების შეტანა, აღდგენა, სარეზერვო პარამეტრები და გაწმენდა გამორთულია.",
                    size=12,
                    color=runtime.muted_text,
                )
            )

        self._refresh_session_labels()
        return self._section_card("სესია", details)

    def _build_db_section(self) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Text("მონაცემთა ბაზის საქაღალდე", size=18, weight=ft.FontWeight.W_700),
                _label_value("აქტიური ბაზა", self._db_path_text),
                _label_value("დაყენებული საქაღალდე", self._db_folder_text),
                ft.Row(
                    controls=[
                        self._action_button(
                            "საქაღალდის შეცვლა",
                            ft.Colors.PRIMARY,
                            self._on_pick_db_folder if self._can_write else None,
                        ),
                    ],
                    wrap=True,
                ),
                self._pending_db_card,
                self._db_feedback,
            ],
            spacing=SPACE_SM,
            tight=True,
        )

    def _build_backup_section(self) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Text("სარეზერვო ასლი", size=18, weight=ft.FontWeight.W_700),
                _label_value("არჩეული საქაღალდე", self._backup_folder_text),
                _label_value("რეალური შენახვის ადგილი", self._backup_destination_text),
                _label_value("ბოლო ხელით შექმნილი", self._last_manual_text),
                _label_value("ბოლო ავტო-ასლი", self._last_auto_text),
                self._backup_health_text,
                _label_value("ჟურნალი", self._backup_log_text),
                ft.Row(
                    controls=[
                        self._action_button(
                            "სარეზერვო საქაღალდის არჩევა",
                            ft.Colors.PRIMARY,
                            self._on_pick_backup_folder if self._can_write else None,
                        ),
                        self._manual_backup_btn,
                        self._action_button(
                            "სარეზერვოდან აღდგენა",
                            ft.Colors.ERROR_CONTAINER,
                            self._on_pick_restore_file if self._can_write else None,
                            text_color=ft.Colors.ON_ERROR_CONTAINER,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                ),
                self._backup_feedback,
                ft.Divider(height=1),
                ft.Text("სარეზერვო ასლების გაწმენდა", size=14, weight=ft.FontWeight.W_700),
                ft.Row(
                    controls=[
                        self._keep_count_field,
                        self._action_button(
                            "მხოლოდ ბოლო N ასლის დატოვება",
                            ft.Colors.ERROR_CONTAINER,
                            self._on_keep_latest_backups if self._can_write else None,
                            text_color=ft.Colors.ON_ERROR_CONTAINER,
                        ),
                        self._keep_months_field,
                        self._action_button(
                            "ბოლო N თვის დატოვება",
                            ft.Colors.ERROR_CONTAINER,
                            self._on_keep_recent_months if self._can_write else None,
                            text_color=ft.Colors.ON_ERROR_CONTAINER,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        self._cleanup_start_field,
                        self._cleanup_end_field,
                        self._action_button(
                            "პერიოდის წაშლა",
                            ft.Colors.ERROR_CONTAINER,
                            self._on_cleanup_backups if self._can_write else None,
                            text_color=ft.Colors.ON_ERROR_CONTAINER,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._cleanup_feedback,
                self._pending_restore_card,
                self._restore_feedback,
            ],
            spacing=SPACE_SM,
            tight=True,
        )

    # ── appearance ──────────────────────────────────────────────────────

    def _make_color_field(self, label: str, key: str) -> ft.TextField:
        return ft.TextField(
            label=label,
            border_radius=RADIUS_MD,
            text_size=13,
            on_change=lambda e, k=key: self._on_custom_field_change(k, e.control.value),
        )

    def _refresh_theme_controls(self) -> None:
        runtime = get_active_theme_runtime()
        self._selection_label.value = (
            "აქტიური რეჟიმი: მზა თემა"
            if self._draft_theme_pref["selection"] == "preset"
            else "აქტიური რეჟიმი: საკუთარი პალიტრა"
        )
        self._selection_label.color = runtime.muted_text

        custom = self._draft_theme_pref["custom"]
        self._seed_field.value = custom["seed_color"]
        self._accent_field.value = custom["accent_color"]
        self._app_bg_field.value = custom["app_bg"]
        self._sidebar_bg_field.value = custom["sidebar_bg"]
        self._manual_backup_btn.bgcolor = runtime.accent

        self._rebuild_preset_row()
        self._rebuild_preview_card()
        self._rebuild_custom_theme_panel()
        self._refresh_view()

    def _rebuild_preset_row(self) -> None:
        cards = [
            self._preset_card(preset_id, label)
            for preset_id, label in [
                ("warm_editorial", "Warm Editorial"),
                ("kodak_classic", "Kodak Classic"),
                ("darkroom_green", "Darkroom Green"),
                ("ocean_film", "Ocean Film"),
                ("mulberry_studio", "Mulberry Studio"),
            ]
        ]
        self._preset_row.controls = cards

    def _preset_card(self, preset_id: str, label: str) -> ft.Control:
        palette = THEME_PRESETS[preset_id]
        is_selected = (
            self._draft_theme_pref["selection"] == "preset"
            and self._draft_theme_pref["preset_id"] == preset_id
        )
        runtime = get_active_theme_runtime()

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            _swatch(palette.seed_color, size=18),
                            _swatch(palette.accent_color, size=18),
                            _swatch(palette.app_bg, size=18),
                            _swatch(palette.sidebar_bg, size=18),
                        ],
                        spacing=SPACE_XS,
                    ),
                    ft.Text(label, size=12, weight=ft.FontWeight.W_600),
                ],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(2, runtime.accent if is_selected else runtime.panel_border),
            border_radius=RADIUS_MD,
            padding=ft.padding.all(SPACE_SM),
            width=168,
            on_click=lambda e, theme_id=preset_id: self._on_select_preset(theme_id),
            ink=True,
        )

    def _rebuild_preview_card(self) -> None:
        preview_runtime = resolve_theme_runtime(self._draft_theme_pref)
        self._preview_card.content = _theme_preview(preview_runtime)
        self._preview_card.bgcolor = preview_runtime.panel_bg
        self._preview_card.border = ft.border.all(1, preview_runtime.panel_border)
        self._preview_card.border_radius = RADIUS_MD
        self._preview_card.padding = ft.padding.all(SPACE_SM)
        self._preview_card.height = 68

    def _rebuild_custom_theme_panel(self) -> None:
        runtime = get_active_theme_runtime()
        self._custom_theme_panel.visible = self._custom_theme_visible
        self._custom_theme_panel.bgcolor = _with_alpha(runtime.accent, 0.05)
        self._custom_theme_panel.border = ft.border.all(1, runtime.panel_border)
        self._custom_theme_panel.border_radius = RADIUS_MD
        self._custom_theme_panel.padding = ft.padding.all(SPACE_MD)
        self._custom_theme_panel.content = ft.Column(
            controls=[
                ft.ResponsiveRow(
                    controls=[
                        ft.Container(content=self._seed_field, col={"sm": 6, "md": 3}),
                        ft.Container(content=self._accent_field, col={"sm": 6, "md": 3}),
                        ft.Container(content=self._app_bg_field, col={"sm": 6, "md": 3}),
                        ft.Container(content=self._sidebar_bg_field, col={"sm": 6, "md": 3}),
                    ],
                    columns=12,
                    run_spacing=SPACE_SM,
                    spacing=SPACE_SM,
                ),
                self._custom_feedback,
                ft.ResponsiveRow(
                    controls=[
                        ft.Container(
                            content=self._swatch_group("ძირითადი ფერი", "seed_color"),
                            col={"sm": 6, "md": 3},
                        ),
                        ft.Container(
                            content=self._swatch_group("აქცენტი", "accent_color"),
                            col={"sm": 6, "md": 3},
                        ),
                        ft.Container(
                            content=self._swatch_group("ფონი", "app_bg"),
                            col={"sm": 6, "md": 3},
                        ),
                        ft.Container(
                            content=self._swatch_group("გვერდითი სვეტი", "sidebar_bg"),
                            col={"sm": 6, "md": 3},
                        ),
                    ],
                    columns=12,
                    run_spacing=SPACE_SM,
                    spacing=SPACE_SM,
                ),
            ],
            spacing=SPACE_SM,
            tight=True,
        )

        toggle_label = (
            "პალიტრის დამალვა" if self._custom_theme_visible else "საკუთარი პალიტრა"
        )
        toggle_color = ft.Colors.WHITE if self._custom_theme_visible else ft.Colors.ON_SURFACE
        self._custom_theme_toggle.content = ft.Text(
            toggle_label,
            size=13,
            weight=ft.FontWeight.W_600,
            color=toggle_color,
        )
        self._custom_theme_toggle.bgcolor = (
            runtime.accent if self._custom_theme_visible else ft.Colors.SURFACE_CONTAINER_HIGH
        )

    def _swatch_group(self, label: str, key: str) -> ft.Control:
        return ft.Column(
            controls=[
                ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row(
                    controls=[
                        _swatch(color, on_click=lambda e, c=color, k=key: self._on_pick_swatch(k, c))
                        for color in _swatch_options(key)
                    ],
                    spacing=SPACE_XS,
                    wrap=True,
                ),
            ],
            spacing=SPACE_XS,
            tight=True,
        )

    def _on_select_preset(self, preset_id: str) -> None:
        self._draft_theme_pref["selection"] = "preset"
        self._draft_theme_pref["preset_id"] = preset_id
        self._theme_feedback.value = ""
        self._custom_feedback.value = ""
        self._apply_preview(self._draft_theme_pref)

    def _on_toggle_custom_theme(self, e: ft.ControlEvent) -> None:
        self._custom_theme_visible = not self._custom_theme_visible
        self._rebuild_custom_theme_panel()
        self._refresh_view()

    def _on_pick_swatch(self, key: str, color: str) -> None:
        field = self._field_for_key(key)
        field.value = color
        self._on_custom_field_change(key, color)

    def _on_custom_field_change(self, key: str, raw_value: str) -> None:
        self._custom_theme_visible = True
        if not self._custom_inputs_are_valid():
            self._custom_feedback.value = "HEX ფერები უნდა იყოს ფორმატში #RRGGBB."
            self._custom_feedback.color = ft.Colors.ERROR
            self._rebuild_custom_theme_panel()
            self._refresh_view()
            return

        self._custom_feedback.value = "საკუთარი პალიტრის წინასწარი ნახვა ჩაირთო."
        self._custom_feedback.color = ft.Colors.PRIMARY

        custom = self._draft_theme_pref["custom"]
        custom["seed_color"] = self._normalized_field(self._seed_field)
        custom["accent_color"] = self._normalized_field(self._accent_field)
        custom["app_bg"] = self._normalized_field(self._app_bg_field)
        custom["sidebar_bg"] = self._normalized_field(self._sidebar_bg_field)
        self._draft_theme_pref["selection"] = "custom"
        self._apply_preview(self._draft_theme_pref)

    def _on_save_theme(self, e: ft.ControlEvent) -> None:
        if not self._can_write:
            self._set_feedback(
                self._theme_feedback,
                "მხოლოდ ნახვის რეჟიმში თემის შენახვა გამორთულია.",
                error=True,
            )
            return
        if not self._custom_inputs_are_valid():
            self._set_feedback(
                self._theme_feedback,
                "შენახვამდე ყველა HEX ფერი სწორად შეიყვანეთ.",
                error=True,
            )
            return

        self._saved_theme_pref = save_user_theme_preference(self._user.id, self._draft_theme_pref)
        self._draft_theme_pref = deepcopy(self._saved_theme_pref)
        self._set_feedback(self._theme_feedback, "თემა შეინახა.")
        self._refresh_theme_controls()

    def _on_cancel_theme(self, e: ft.ControlEvent) -> None:
        self._draft_theme_pref = deepcopy(self._saved_theme_pref)
        self._theme_feedback.value = ""
        self._set_feedback(self._custom_feedback, "ცვლილებები გაუქმდა.")
        self._apply_preview(self._saved_theme_pref)

    def _on_reset_theme(self, e: ft.ControlEvent) -> None:
        self._draft_theme_pref = default_theme_preference()
        self._theme_feedback.value = ""
        self._set_feedback(self._custom_feedback, "ნაგულისხმევი თემა ჩაიტვირთა.")
        self._apply_preview(self._draft_theme_pref)

    def _apply_preview(self, pref: dict[str, Any]) -> None:
        runtime = resolve_theme_runtime(pref)
        apply_page_theme(self._page, runtime)
        self._refresh_theme_controls()
        if self._on_theme_preview is not None:
            self._on_theme_preview()
        else:
            self._refresh_view()

    def _field_for_key(self, key: str) -> ft.TextField:
        return {
            "seed_color": self._seed_field,
            "accent_color": self._accent_field,
            "app_bg": self._app_bg_field,
            "sidebar_bg": self._sidebar_bg_field,
        }[key]

    def _normalized_field(self, field: ft.TextField) -> str:
        raw = (field.value or "").strip().upper()
        return raw if raw.startswith("#") else f"#{raw}"

    def _custom_inputs_are_valid(self) -> bool:
        return all(
            is_valid_hex_color(field.value)
            for field in (
                self._seed_field,
                self._accent_field,
                self._app_bg_field,
                self._sidebar_bg_field,
            )
        )

    # ── system settings ────────────────────────────────────────────────

    def _refresh_config_labels(self) -> None:
        self._config = load_config()
        configured_db_folder = self._config.get("db_folder")
        configured_backup_root = self._config.get("backup_folder")
        backup_dir = backup_storage_dir(self._config)
        log_path = backup_log_path(self._config)
        runtime = get_active_theme_runtime()

        self._db_path_text.value = str(DB_PATH)
        self._db_folder_text.value = (
            str(Path(configured_db_folder).expanduser())
            if configured_db_folder
            else "ჯერ არჩეული არ არის — გამოიყენება ლოკალური ფაილი"
        )
        self._backup_folder_text.value = (
            str(Path(configured_backup_root).expanduser())
            if configured_backup_root
            else "ჯერ არჩეული არ არის"
        )
        self._backup_destination_text.value = (
            str(backup_dir) if backup_dir else "ჯერ არჩეული არ არის"
        )
        self._last_manual_text.value = _describe_backup_record(
            self._config.get("last_manual_backup")
        )
        self._last_auto_text.value = _describe_backup_record(
            self._config.get("last_auto_backup")
        )
        health_message, health_error = _backup_health(self._config)
        self._backup_health_text.value = health_message
        self._backup_health_text.color = ft.Colors.ERROR if health_error else ft.Colors.PRIMARY
        self._backup_log_text.value = str(log_path) if log_path else "ჯერ არჩეული არ არის"

        enabled = backup_dir is not None and self._can_write
        self._manual_backup_btn.opacity = 1.0 if enabled else 0.45
        self._manual_backup_btn.bgcolor = runtime.accent
        self._manual_backup_btn.on_click = self._on_manual_backup if enabled else None

        self._refresh_session_labels()

    def _refresh_session_labels(self) -> None:
        if not hasattr(self, "_sync_status_text"):
            return
        if self._access_mode == AccessMode.read_only:
            self._editor_lock = read_session_lock(DB_PATH) or self._editor_lock
        message, error = _sync_status()
        self._sync_status_text.value = message
        self._sync_status_text.color = ft.Colors.ERROR if error else ft.Colors.PRIMARY

    def _set_feedback(self, control: ft.Text, message: str, *, error: bool = False) -> None:
        control.value = message
        control.color = ft.Colors.ERROR if error else ft.Colors.PRIMARY
        self._refresh_view()

    def _ensure_write_allowed(self, control: ft.Text) -> bool:
        if self._can_write:
            return True
        self._set_feedback(
            control,
            "აპლიკაცია გახსნილია მხოლოდ ნახვის რეჟიმში.",
            error=True,
        )
        return False

    async def _pick_db_folder(self) -> None:
        if not self._ensure_write_allowed(self._db_feedback):
            return
        runtime = get_active_theme_runtime()
        selected = await self._db_picker.get_directory_path(
            dialog_title="აირჩიეთ მონაცემთა ბაზის საქაღალდე",
            initial_directory=str(DB_PATH.parent),
        )
        if not selected:
            return

        self._pending_db_folder = Path(selected).expanduser()
        existing_db = self._pending_db_folder / DB_PATH.name
        note = [
            ft.Text(
                f"ახალი საქაღალდე: {self._pending_db_folder}",
                size=12,
                selectable=True,
            )
        ]
        if existing_db.exists():
            note.append(
                ft.Text(
                    f"საქაღალდეში უკვე არსებობს {DB_PATH.name}; "
                    "გადატვირთვის შემდეგ სწორედ ის გაიხსნება.",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            )

        self._pending_db_card.content = ft.Column(
            controls=[
                ft.Text("გადავიტანოთ მიმდინარე ბაზა ახალ საქაღალდეში?", weight=ft.FontWeight.W_600),
                *note,
                ft.Row(
                    controls=[
                        self._action_button(
                            "დიახ, გადავიტანო",
                            runtime.accent,
                            self._on_confirm_move_db,
                        ),
                        self._action_button(
                            "არა, ცარიელი ბაზა",
                            ft.Colors.PRIMARY,
                            self._on_confirm_fresh_db,
                        ),
                        self._action_button(
                            "გაუქმება",
                            ft.Colors.SURFACE_CONTAINER_HIGH,
                            self._on_cancel_pending_db,
                            text_color=ft.Colors.ON_SURFACE,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                ),
            ],
            spacing=SPACE_SM,
            tight=True,
        )
        self._pending_db_card.bgcolor = ft.Colors.SURFACE_CONTAINER
        self._pending_db_card.border = ft.border.all(1, runtime.panel_border)
        self._pending_db_card.border_radius = RADIUS_MD
        self._pending_db_card.padding = ft.padding.all(SPACE_MD)
        self._pending_db_card.visible = True
        self._refresh_view()

    async def _pick_backup_folder(self) -> None:
        if not self._ensure_write_allowed(self._backup_feedback):
            return
        selected = await self._backup_picker.get_directory_path(
            dialog_title="აირჩიეთ სარეზერვო საქაღალდე",
            initial_directory=str(Path.home()),
        )
        if not selected:
            return

        self._config["backup_folder"] = str(Path(selected).expanduser())
        try:
            save_config(self._config)
        except Exception:
            self._set_feedback(
                self._backup_feedback,
                "სარეზერვო საქაღალდის შენახვა ვერ მოხერხდა.",
                error=True,
            )
            return
        self._refresh_config_labels()
        self._refresh_view()
        self._set_feedback(self._backup_feedback, "სარეზერვო საქაღალდე განახლდა.")

    def _on_pick_db_folder(self, e: ft.ControlEvent) -> None:
        self._page.run_task(self._pick_db_folder)

    def _on_pick_backup_folder(self, e: ft.ControlEvent) -> None:
        self._page.run_task(self._pick_backup_folder)

    def _on_pick_restore_file(self, e: ft.ControlEvent) -> None:
        self._page.run_task(self._pick_restore_file)

    def _on_confirm_move_db(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._db_feedback):
            return
        if self._pending_db_folder is None:
            return
        try:
            snapshot_database_to(self._pending_db_folder / DB_PATH.name)
            self._save_db_folder(self._pending_db_folder)
            self._set_feedback(
                self._db_feedback,
                "მონაცემთა ბაზა გადაიტანეს. ცვლილება იმუშავებს აპლიკაციის გადატვირთვის შემდეგ.",
            )
        except Exception as exc:
            self._set_feedback(self._db_feedback, str(exc), error=True)
            return
        self._clear_pending_db_card()

    def _on_confirm_fresh_db(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._db_feedback):
            return
        if self._pending_db_folder is None:
            return
        try:
            self._save_db_folder(self._pending_db_folder)
        except Exception:
            self._set_feedback(
                self._db_feedback,
                "ახალი საქაღალდის შენახვა ვერ მოხერხდა.",
                error=True,
            )
            return
        self._set_feedback(
            self._db_feedback,
            "ახალი საქაღალდე შეინახა. ცვლილება იმუშავებს აპლიკაციის გადატვირთვის შემდეგ.",
        )
        self._clear_pending_db_card()

    def _on_cancel_pending_db(self, e: ft.ControlEvent) -> None:
        self._clear_pending_db_card()
        self._set_feedback(self._db_feedback, "ცვლილება გაუქმდა.")

    def _clear_pending_db_card(self) -> None:
        self._pending_db_folder = None
        self._pending_db_card.visible = False
        self._refresh_view()

    def _save_db_folder(self, folder: Path) -> None:
        self._config["db_folder"] = str(folder.expanduser())
        save_config(self._config)
        self._refresh_config_labels()
        self._refresh_view()

    def _on_manual_backup(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._backup_feedback):
            return
        try:
            record = create_manual_backup()
        except BackupError as exc:
            self._set_feedback(self._backup_feedback, str(exc), error=True)
            return

        self._refresh_config_labels()
        self._refresh_view()
        self._set_feedback(
            self._backup_feedback,
            f"სარეზერვო ასლი შეიქმნა: {record['path']}",
        )

    # ── full data export ───────────────────────────────────────────────

    def _on_pick_export_all(self, e: ft.ControlEvent) -> None:
        self._page.run_task(self._pick_export_all)

    async def _pick_export_all(self) -> None:
        default_name = f"kodak_export_{clock.today():%Y-%m-%d}.xlsx"
        initial = backup_storage_dir(self._config) or DB_PATH.parent
        try:
            target = await self._export_picker.save_file(
                dialog_title="შეინახეთ Excel ფაილი",
                file_name=default_name,
                initial_directory=str(initial),
                allowed_extensions=["xlsx"],
            )
        except Exception as exc:
            self._set_feedback(self._export_feedback, f"ექსპორტი ვერ მოხერხდა: {exc}", error=True)
            return
        if not target:
            return

        path = Path(target)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")

        try:
            export_all_to_xlsx(path)
        except Exception as exc:
            self._set_feedback(self._export_feedback, f"ფაილის შენახვა ვერ მოხერხდა: {exc}", error=True)
            return

        self._set_feedback(self._export_feedback, f"შენახულია: {path.name}")

    def _on_cleanup_backups(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._cleanup_feedback):
            return
        try:
            start = date.fromisoformat((self._cleanup_start_field.value or "").strip())
            end = date.fromisoformat((self._cleanup_end_field.value or "").strip())
        except ValueError:
            self._set_feedback(
                self._cleanup_feedback,
                "თარიღები შეიყვანეთ ფორმატით YYYY-MM-DD.",
                error=True,
            )
            return

        try:
            result = clean_backups_between(start, end)
        except BackupError as exc:
            self._set_feedback(self._cleanup_feedback, str(exc), error=True)
            return

        self._show_cleanup_result(result)

    def _on_keep_latest_backups(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._cleanup_feedback):
            return
        try:
            limit = int((self._keep_count_field.value or "").strip())
        except ValueError:
            self._set_feedback(
                self._cleanup_feedback,
                "ასლების რაოდენობა უნდა იყოს მთელი რიცხვი.",
                error=True,
            )
            return

        try:
            result = keep_latest_backups(limit)
        except BackupError as exc:
            self._set_feedback(self._cleanup_feedback, str(exc), error=True)
            return

        self._show_cleanup_result(result)

    def _on_keep_recent_months(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._cleanup_feedback):
            return
        try:
            months = int((self._keep_months_field.value or "").strip())
        except ValueError:
            self._set_feedback(
                self._cleanup_feedback,
                "თვეების რაოდენობა უნდა იყოს მთელი რიცხვი.",
                error=True,
            )
            return

        try:
            result = keep_backups_for_recent_months(months)
        except BackupError as exc:
            self._set_feedback(self._cleanup_feedback, str(exc), error=True)
            return

        self._show_cleanup_result(result)

    def _show_cleanup_result(self, result: dict[str, Any]) -> None:
        deleted = int(result["deleted"])
        size_mb = int(result["bytes"]) / (1024 * 1024)
        errors = result.get("errors") or []
        if errors:
            self._set_feedback(
                self._cleanup_feedback,
                f"წაიშალა {deleted} ფაილი ({size_mb:.1f} MB), მაგრამ ნაწილი ვერ წაიშალა.",
                error=True,
            )
        else:
            self._set_feedback(
                self._cleanup_feedback,
                f"წაიშალა {deleted} ფაილი ({size_mb:.1f} MB).",
            )

    async def _pick_restore_file(self) -> None:
        if not self._ensure_write_allowed(self._restore_feedback):
            return
        runtime = get_active_theme_runtime()
        initial_dir = backup_storage_dir(self._config) or DB_PATH.parent
        files = await self._restore_picker.pick_files(
            dialog_title="აირჩიეთ სარეზერვო ასლი",
            initial_directory=str(initial_dir),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["db"],
            allow_multiple=False,
        )
        if not files:
            return

        selected = files[0].path
        if not selected:
            self._set_feedback(
                self._restore_feedback,
                "არჩეული ფაილის ბილიკი ვერ წაიკითხა.",
                error=True,
            )
            return

        self._pending_restore_file = Path(selected).expanduser()
        safety_hint_root = backup_storage_dir(self._config) or DB_PATH.parent
        try:
            stat = self._pending_restore_file.stat()
            modified = clock.to_local(datetime.fromtimestamp(stat.st_mtime, tz=UTC))
            preview = (
                f"ზომა: {stat.st_size / (1024 * 1024):.1f} MB  ·  "
                f"შეცვლილია: {modified.strftime('%Y-%m-%d %H:%M')}"
            )
        except OSError:
            preview = "ფაილის დეტალები ვერ წავიკითხე."
        self._pending_restore_card.content = ft.Column(
            controls=[
                ft.Text("მონაცემთა ბაზის აღდგენა", weight=ft.FontWeight.W_700),
                ft.Text(
                    f"აღდგენის წყარო: {self._pending_restore_file}",
                    size=12,
                    selectable=True,
                ),
                ft.Text(
                    preview,
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    selectable=True,
                ),
                ft.Text(
                    f"აღდგენამდე მიმდინარე ბაზა შეინახება pre_restore ასლად აქ: {safety_hint_root}",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    selectable=True,
                ),
                ft.Text(
                    "ყურადღება: ეს მოქმედება გადააწერს მიმდინარე მონაცემთა ბაზას. "
                    "შემდეგ აპლიკაციის თავიდან გახსნა იქნება საჭირო.",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Row(
                    controls=[
                        self._action_button(
                            "დიახ, აღდგენა",
                            ft.Colors.ERROR,
                            self._on_confirm_restore,
                        ),
                        self._action_button(
                            "გაუქმება",
                            ft.Colors.SURFACE_CONTAINER_HIGH,
                            self._on_cancel_restore,
                            text_color=ft.Colors.ON_SURFACE,
                        ),
                    ],
                    spacing=SPACE_SM,
                    wrap=True,
                ),
            ],
            spacing=SPACE_SM,
            tight=True,
        )
        self._pending_restore_card.bgcolor = _with_alpha(runtime.accent, 0.08)
        self._pending_restore_card.border = ft.border.all(1, runtime.panel_border)
        self._pending_restore_card.border_radius = RADIUS_MD
        self._pending_restore_card.padding = ft.padding.all(SPACE_MD)
        self._pending_restore_card.visible = True
        self._refresh_view()

    def _on_confirm_restore(self, e: ft.ControlEvent) -> None:
        if not self._ensure_write_allowed(self._restore_feedback):
            return
        if self._pending_restore_file is None:
            return
        try:
            result = restore_database_from(self._pending_restore_file)
        except BackupError as exc:
            self._set_feedback(self._restore_feedback, str(exc), error=True)
            return

        self._clear_pending_restore()
        self._set_feedback(
            self._restore_feedback,
            "ბაზა აღდგა. აპლიკაცია ახლა უნდა დაიხუროს და თავიდან გაიხსნას.",
        )
        self._show_restore_complete_dialog(result["restored_from"], result["safety_backup"])

    def _on_cancel_restore(self, e: ft.ControlEvent) -> None:
        self._clear_pending_restore()
        self._set_feedback(self._restore_feedback, "აღდგენა გაუქმდა.")

    def _clear_pending_restore(self) -> None:
        self._pending_restore_file = None
        self._pending_restore_card.visible = False
        self._refresh_view()

    def _show_restore_complete_dialog(self, restored_from: str, safety_backup: str) -> None:
        def close_now(e: ft.ControlEvent) -> None:
            self._page.pop_dialog()
            if self._on_request_close is not None:
                self._on_request_close()

        self._page.show_dialog(
            ft.AlertDialog(
                modal=True,
                open=True,
                title=ft.Text("აღდგენა დასრულდა", weight=ft.FontWeight.W_700),
                content=ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Text("მონაცემთა ბაზა აღდგა არჩეული სარეზერვო ასლიდან.", size=14),
                            ft.Text(
                                f"აღდგენილი ფაილი: {restored_from}",
                                size=12,
                                selectable=True,
                            ),
                            ft.Text(
                                f"უსაფრთხოების ასლი: {safety_backup}",
                                size=12,
                                selectable=True,
                            ),
                            ft.Text(
                                "ახლა დახურეთ აპლიკაცია და თავიდან გახსენით.",
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=SPACE_SM,
                        tight=True,
                    ),
                    width=460,
                ),
                actions=[ft.FilledButton("დახურვა", on_click=close_now)],
                actions_alignment=ft.MainAxisAlignment.END,
                shape=ft.RoundedRectangleBorder(radius=RADIUS_MD),
            )
        )

    def _on_release_edit_lock(self, e: ft.ControlEvent) -> None:
        log_event("manual_release_edit_lock", "ok", self._user.username)
        if self._on_request_close is not None:
            self._on_request_close()

    # ── shared ui helpers ─────────────────────────────────────────────

    def _action_button(
        self,
        label: str,
        bgcolor: str,
        on_click,
        *,
        text_color: str = ft.Colors.WHITE,
    ) -> ft.Container:
        return ft.Container(
            content=ft.Text(label, size=13, weight=ft.FontWeight.W_600, color=text_color),
            bgcolor=bgcolor,
            border_radius=RADIUS_SM,
            padding=ft.padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_SM),
            on_click=on_click,
            ink=on_click is not None,
            opacity=1.0 if on_click is not None else 0.45,
        )

    def _section_card(self, title: str, controls: list[ft.Control]) -> ft.Control:
        runtime = get_active_theme_runtime()
        return ft.Container(
            content=ft.Column(
                controls=[ft.Text(title, size=18, weight=ft.FontWeight.W_700), *controls],
                spacing=SPACE_SM,
                tight=True,
            ),
            bgcolor=runtime.panel_bg,
            border=ft.border.all(1, runtime.panel_border),
            border_radius=RADIUS_LG,
            padding=ft.padding.all(SPACE_LG),
        )

    def _refresh_view(self) -> None:
        if self._root is not None and self._root.page is not None:
            self._root.update()


def _swatch_options(key: str) -> list[str]:
    if key == "seed_color":
        return [preset.seed_color for preset in THEME_PRESETS.values()]
    if key == "accent_color":
        return [preset.accent_color for preset in THEME_PRESETS.values()]
    if key == "app_bg":
        return [preset.app_bg for preset in THEME_PRESETS.values()]
    return [preset.sidebar_bg for preset in THEME_PRESETS.values()]


def _theme_preview(runtime: ThemeRuntime) -> ft.Control:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    bgcolor=runtime.sidebar_bg,
                    border_radius=RADIUS_SM,
                    width=54,
                    height=40,
                ),
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                bgcolor=runtime.panel_bg,
                                border=ft.border.all(1, runtime.panel_border),
                                border_radius=RADIUS_SM,
                                height=40,
                                expand=2,
                            ),
                            ft.Container(
                                bgcolor=runtime.sidebar_active_bg,
                                border_radius=RADIUS_SM,
                                height=40,
                                expand=1,
                            ),
                            ft.Container(
                                bgcolor=runtime.accent,
                                border_radius=RADIUS_SM,
                                height=40,
                                expand=1,
                            ),
                        ],
                        spacing=SPACE_SM,
                    ),
                    expand=True,
                    bgcolor=runtime.app_bg,
                    border_radius=RADIUS_MD,
                    padding=ft.padding.all(SPACE_XS),
                ),
            ],
            spacing=SPACE_SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=runtime.app_bg,
        border_radius=RADIUS_MD,
        padding=ft.padding.all(SPACE_SM),
    )


def _mini_metric(value: str, label: str, runtime: ThemeRuntime) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(value, size=12, weight=ft.FontWeight.W_700),
                ft.Text(label, size=9, color=runtime.muted_text),
            ],
            spacing=2,
            tight=True,
        ),
        bgcolor=runtime.panel_bg,
        border=ft.border.all(1, runtime.panel_border),
        border_radius=RADIUS_SM,
        padding=ft.padding.symmetric(horizontal=SPACE_SM, vertical=SPACE_XS),
        expand=True,
    )


def _swatch(color: str, *, size: int = 22, on_click=None) -> ft.Control:
    return ft.Container(
        width=size,
        height=size,
        border_radius=size / 2,
        bgcolor=color,
        border=ft.border.all(1, "#1E17111A"),
        on_click=on_click,
        ink=on_click is not None,
    )


def _with_alpha(color: str, alpha: float) -> str:
    raw = color.lstrip("#")
    pct = max(0, min(255, round(alpha * 255)))
    return f"#{pct:02X}{raw.upper()}"


def _label_value(label: str, value: ft.Control) -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=ft.Colors.ON_SURFACE_VARIANT),
            value,
        ],
        spacing=SPACE_XS,
        tight=True,
    )


def _describe_backup_record(record: Any) -> str:
    if not isinstance(record, dict):
        return "ჯერ არ შექმნილა"
    path = record.get("path")
    at = record.get("at")
    if not path or not at:
        return "ჯერ არ შექმნილა"
    return f"{path}  •  {_relative_time(str(at))}"


def _relative_time(timestamp: str) -> str:
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - then.astimezone(UTC)
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "ახლახან"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} წუთის წინ"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} საათის წინ"
    days = hours // 24
    return f"{days} დღის წინ"


def _backup_health(cfg: dict[str, Any]) -> tuple[str, bool]:
    records = [
        item
        for item in (cfg.get("last_manual_backup"), cfg.get("last_auto_backup"))
        if isinstance(item, dict) and item.get("at")
    ]
    if not records:
        return "გაფრთხილება: სარეზერვო ასლი ჯერ არ შექმნილა.", True

    latest: datetime | None = None
    for record in records:
        try:
            at = datetime.fromisoformat(str(record["at"]))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        latest = at if latest is None or at > latest else latest

    if latest is None:
        return "გაფრთხილება: ბოლო სარეზერვო ასლის დრო ვერ წავიკითხე.", True

    age = datetime.now(UTC) - latest.astimezone(UTC)
    if age.total_seconds() > 24 * 60 * 60:
        return "გაფრთხილება: ბოლო სარეზერვო ასლი 24 საათზე ძველია.", True
    return "სარეზერვო ასლების მდგომარეობა კარგია.", False


def _sync_status() -> tuple[str, bool]:
    folder = DB_PATH.parent
    if not folder.exists():
        return f"საქაღალდე ვერ მოიძებნა: {folder}", True
    if not os.access(folder, os.R_OK):
        return f"საქაღალდე არ იკითხება: {folder}", True

    path_text = str(folder).lower()
    looks_like_drive = "google drive" in path_text or "drivefs" in path_text
    if looks_like_drive and not os.access(folder, os.W_OK):
        return "Google Drive საქაღალდე ჩანს, მაგრამ ჩაწერა მიუწვდომელია.", True
    if looks_like_drive:
        return "Google Drive საქაღალდე ხელმისაწვდომია. Drive-ის სინქრონიზაცია მაინც გადაამოწმეთ.", False
    return "მონაცემთა ბაზის საქაღალდე ხელმისაწვდომია.", False
