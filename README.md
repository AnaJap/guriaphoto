# Guriaphoto Kodak

A lightweight desktop app for Guriaphoto Kodak — a small photo studio — to replace the legacy Excel workbook used for tracking revenue, customer credits (ნისია), stock, and salaries.

## Tech stack

- **Python 3.11+**
- **Flet** — cross-platform desktop UI (Windows / Mac)
- **SQLModel + SQLite** — local offline database
- **uv** — package manager
- **Ruff** — linting & formatting

## Getting started

Install [uv](https://docs.astral.sh/uv/) if you don't have it:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then from the project root:

```bash
# install dependencies into a local virtual environment
UV_PROJECT_ENVIRONMENT=venv uv sync

# run the app
UV_PROJECT_ENVIRONMENT=venv uv run kodak
```

## Project layout

```
Kodak/
├── pyproject.toml      # project metadata + deps
├── src/kodak/          # application source
│   ├── main.py         # Flet entry point
│   ├── db.py           # SQLite + SQLModel session
│   ├── models/         # SQLModel schemas
│   ├── services/       # business logic
│   └── ui/             # Flet views and components
├── data/               # local SQLite file (gitignored)
├── tests/              # pytest tests
├── feature-list.md     # spec for the app
└── Kodak.xlsx          # original Excel (reference)
```

## Status

Early scaffold — see `feature-list.md` for the full feature plan and MVP priorities.
