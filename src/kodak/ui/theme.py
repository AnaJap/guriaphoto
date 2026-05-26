"""Runtime theme system and shared visual tokens for the Kodak app."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import flet as ft

from kodak.access import require_write_access
from kodak.db import get_session
from kodak.models.setting import Setting

THEME_VERSION = 1
DEFAULT_PRESET_ID = "warm_editorial"
_THEME_SETTING_PREFIX = "ui_theme:user:"


@dataclass(frozen=True)
class ThemePalette:
    seed_color: str
    accent_color: str
    app_bg: str
    sidebar_bg: str


@dataclass(frozen=True)
class ThemeRuntime:
    preference: dict[str, Any]
    palette: ThemePalette
    theme: ft.Theme
    accent: str
    app_bg: str
    sidebar_bg: str
    sidebar_fg: str
    sidebar_active_bg: str
    sidebar_active_fg: str
    panel_bg: str
    panel_border: str
    muted_text: str


THEME_PRESETS: dict[str, ThemePalette] = {
    "warm_editorial": ThemePalette("#8B5E3C", "#E8960C", "#F6EFE7", "#E4D7C8"),
    "kodak_classic": ThemePalette("#B32025", "#F5C542", "#FFF7E8", "#6E1519"),
    "darkroom_green": ThemePalette("#31543C", "#D7A441", "#F3F1EA", "#243A2C"),
    "ocean_film": ThemePalette("#2E5B6F", "#F29A38", "#F2F6F7", "#1F4352"),
    "mulberry_studio": ThemePalette("#6E425E", "#E0A037", "#F7F0F4", "#4F3044"),
}

SEED_COLOR = THEME_PRESETS[DEFAULT_PRESET_ID].seed_color
ACCENT_GOLD = THEME_PRESETS[DEFAULT_PRESET_ID].accent_color

# Spacing scale (4pt grid).
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 16
SPACE_LG = 24
SPACE_XL = 32

# Radius scale.
RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16

_active_runtime: ThemeRuntime | None = None


def build_theme() -> ft.Theme:
    return resolve_theme_runtime(default_theme_preference()).theme


def default_theme_preference() -> dict[str, Any]:
    palette = THEME_PRESETS[DEFAULT_PRESET_ID]
    return {
        "version": THEME_VERSION,
        "selection": "preset",
        "preset_id": DEFAULT_PRESET_ID,
        "custom": {
            "seed_color": palette.seed_color,
            "accent_color": palette.accent_color,
            "app_bg": palette.app_bg,
            "sidebar_bg": palette.sidebar_bg,
        },
    }


def theme_setting_key(user_id: int) -> str:
    return f"{_THEME_SETTING_PREFIX}{user_id}"


def normalize_theme_preference(data: Any) -> dict[str, Any]:
    pref = default_theme_preference()
    if not isinstance(data, dict):
        return pref

    selection = data.get("selection")
    if selection in {"preset", "custom"}:
        pref["selection"] = selection

    preset_id = data.get("preset_id")
    if preset_id in THEME_PRESETS:
        pref["preset_id"] = preset_id

    custom = data.get("custom")
    if isinstance(custom, dict):
        for key in ("seed_color", "accent_color", "app_bg", "sidebar_bg"):
            pref["custom"][key] = _normalize_hex(custom.get(key), pref["custom"][key])

    pref["version"] = THEME_VERSION
    return pref


def load_user_theme_preference(user_id: int) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(Setting, theme_setting_key(user_id))
    if row is None:
        return default_theme_preference()
    try:
        raw = json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return default_theme_preference()
    return normalize_theme_preference(raw)


def save_user_theme_preference(user_id: int, pref: dict[str, Any]) -> dict[str, Any]:
    require_write_access()
    normalized = normalize_theme_preference(pref)
    payload = json.dumps(normalized, ensure_ascii=False)
    now = datetime.now(UTC)
    key = theme_setting_key(user_id)
    with get_session() as session:
        row = session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=payload, updated_at=now)
        else:
            row.value = payload
            row.updated_at = now
        session.add(row)
        session.commit()
    return normalized


def resolve_theme_runtime(pref: dict[str, Any]) -> ThemeRuntime:
    normalized = normalize_theme_preference(pref)
    palette = _resolve_palette(normalized)

    sidebar_fg = _readable_foreground(palette.sidebar_bg)
    sidebar_active_bg = _mix_colors(palette.sidebar_bg, palette.accent_color, 0.52)
    sidebar_active_fg = _readable_foreground(sidebar_active_bg)
    panel_bg = _mix_colors(palette.app_bg, "#FFFFFF", 0.62)
    panel_border = _mix_colors(palette.seed_color, palette.app_bg, 0.20)
    muted_text = _mix_colors(palette.app_bg, _readable_foreground(palette.app_bg), 0.62)

    theme = ft.Theme(
        color_scheme_seed=palette.seed_color,
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
        font_family=".AppleSystemUIFont",
    )

    return ThemeRuntime(
        preference=deepcopy(normalized),
        palette=palette,
        theme=theme,
        accent=palette.accent_color,
        app_bg=palette.app_bg,
        sidebar_bg=palette.sidebar_bg,
        sidebar_fg=sidebar_fg,
        sidebar_active_bg=sidebar_active_bg,
        sidebar_active_fg=sidebar_active_fg,
        panel_bg=panel_bg,
        panel_border=panel_border,
        muted_text=muted_text,
    )


def apply_page_theme(page: ft.Page, runtime: ThemeRuntime) -> None:
    global _active_runtime
    _active_runtime = runtime
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = runtime.theme
    page.bgcolor = runtime.app_bg


def get_active_theme_runtime() -> ThemeRuntime:
    global _active_runtime
    if _active_runtime is None:
        _active_runtime = resolve_theme_runtime(default_theme_preference())
    return _active_runtime


def is_valid_hex_color(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip().lstrip("#")
    return len(raw) == 6 and all(ch in "0123456789ABCDEFabcdef" for ch in raw)


def _resolve_palette(pref: dict[str, Any]) -> ThemePalette:
    if pref["selection"] == "preset":
        return THEME_PRESETS.get(pref["preset_id"], THEME_PRESETS[DEFAULT_PRESET_ID])
    custom = pref["custom"]
    return ThemePalette(
        seed_color=custom["seed_color"],
        accent_color=custom["accent_color"],
        app_bg=custom["app_bg"],
        sidebar_bg=custom["sidebar_bg"],
    )


def _normalize_hex(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    raw = value.strip().upper()
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if is_valid_hex_color(raw):
        return raw
    return fallback


def _mix_colors(color_a: str, color_b: str, amount_b: float) -> str:
    amount_b = max(0.0, min(1.0, amount_b))
    amount_a = 1.0 - amount_b
    a_r, a_g, a_b = _hex_to_rgb(color_a)
    b_r, b_g, b_b = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        round(a_r * amount_a + b_r * amount_b),
        round(a_g * amount_a + b_g * amount_b),
        round(a_b * amount_a + b_b * amount_b),
    )


def _readable_foreground(bg_hex: str) -> str:
    return "#1E1711" if _relative_luminance(bg_hex) > 0.45 else "#F8F2EB"


def _relative_luminance(color_hex: str) -> float:
    def srgb(channel: int) -> float:
        value = channel / 255
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = _hex_to_rgb(color_hex)
    return 0.2126 * srgb(red) + 0.7152 * srgb(green) + 0.0722 * srgb(blue)


def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    raw = color_hex.strip().lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02X}{green:02X}{blue:02X}"
