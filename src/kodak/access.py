"""Process-wide access mode for single-writer / multi-reader safety."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AccessMode(StrEnum):
    edit = "edit"
    read_only = "read_only"


class ReadOnlyError(RuntimeError):
    """Raised when a write is attempted while the app is in read-only mode."""


@dataclass(slots=True)
class AccessState:
    mode: AccessMode = AccessMode.edit
    editor_lock: Any | None = None


_STATE = AccessState()


def set_access_mode(mode: AccessMode, *, editor_lock: Any | None = None) -> None:
    _STATE.mode = mode
    _STATE.editor_lock = editor_lock


def get_access_mode() -> AccessMode:
    return _STATE.mode


def get_editor_lock() -> Any | None:
    return _STATE.editor_lock


def is_read_only() -> bool:
    return _STATE.mode == AccessMode.read_only


def require_write_access() -> None:
    if is_read_only():
        raise ReadOnlyError("აპლიკაცია გახსნილია მხოლოდ ნახვის რეჟიმში.")
