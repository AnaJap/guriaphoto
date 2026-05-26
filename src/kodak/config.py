"""Per-machine JSON config — settings that must outlive the database.

Lives in the platform user-data directory so each Mac keeps its own
DB-folder pointer. The DB path itself can't be stored inside the DB
(chicken-and-egg), and we don't want a restored DB to clobber per-machine
preferences either.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _config_dir(*, create: bool = True) -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "Kodak"
    elif sys.platform.startswith("win"):
        d = Path(os.environ.get("APPDATA", str(Path.home()))) / "Kodak"
    else:
        d = Path.home() / ".local" / "share" / "Kodak"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _config_file(*, create_dir: bool = False) -> Path:
    return _config_dir(create=create_dir) / "config.json"


def load_config() -> dict[str, Any]:
    p = _config_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(cfg: dict[str, Any]) -> None:
    """Atomic write: tmp-file + os.replace, so a crash mid-write
    can't corrupt the existing config."""
    p = _config_file(create_dir=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, p)
    except Exception:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise
