"""SQLite + SQLModel session setup.

DB path resolution priority (highest first):
1. ``KODAK_DB_PATH`` env var (CI / dev override).
2. ``config.json["db_folder"] / "kodak.db"`` — user-configured location
   (e.g. a Google-Drive-synced folder).
3. Source-checkout dev override: ``<project>/data/kodak.db`` if a sibling
   ``pyproject.toml`` is present.
4. Default: ``<config_dir>/kodak.db`` — per-machine local fallback so the
   app boots even before any configuration.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from kodak.access import is_read_only
from kodak.config import _config_dir, load_config


def _resolve_db_path() -> Path:
    env = os.environ.get("KODAK_DB_PATH")
    if env:
        p = Path(env).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    cfg = load_config()
    folder = cfg.get("db_folder")
    if folder:
        d = Path(folder).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d / "kodak.db"

    candidate_root = Path(__file__).resolve().parents[2]
    if (candidate_root / "pyproject.toml").exists():
        d = candidate_root / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d / "kodak.db"

    return _config_dir() / "kodak.db"


DB_PATH = _resolve_db_path()
DB_URL  = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)
_read_only_engine = None


def _get_read_only_engine():
    global _read_only_engine
    if _read_only_engine is None:
        uri = f"file:{DB_PATH}?mode=ro"
        _read_only_engine = create_engine(
            "sqlite://",
            echo=False,
            creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False),
        )
    return _read_only_engine


def _run_migrations() -> None:
    """Apply incremental schema changes that ``create_all`` cannot handle.

    Each block is idempotent (PRAGMA-checks before ALTER) so re-running is
    always safe.
    """
    with engine.connect() as conn:
        raw = conn.connection  # underlying sqlite3.Connection
        raw.execute("PRAGMA journal_mode=DELETE")

        existing = {row[1] for row in raw.execute("PRAGMA table_info(credit)")}
        if "forgiven_at" not in existing:
            raw.execute("ALTER TABLE credit ADD COLUMN forgiven_at TEXT")
        if "forgiven_by_user_id" not in existing:
            raw.execute(
                "ALTER TABLE credit ADD COLUMN forgiven_by_user_id INTEGER "
                "REFERENCES user(id)"
            )
        raw.commit()


def init_db() -> None:
    """Create tables, run migrations, and seed initial data."""
    from kodak import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _run_migrations()

    from kodak.services.auth import seed_users
    from kodak.services.seed import seed_products

    with Session(engine) as session:
        seed_users(session)
        seed_products(session)


def get_session() -> Session:
    """Return a new Session. Caller is responsible for closing it."""
    if is_read_only():
        return Session(_get_read_only_engine())
    return Session(engine)
