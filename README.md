# Guriaphoto Kodak (გურიაფოტო კოდაკი)

A lightweight desktop app for **Guriaphoto Kodak**, a small photo studio, replacing the
legacy Excel workbook used to track sales, customer credits (ნისია), products, and salaries.
The UI is in Georgian.

## Features

- **Daily sales entry** — tap-to-add product picker, live order total, mandatory
  amount-received with automatic credit (ნისია) calculation, optional note.
- **Credits (ნისია)** — track open / cleared / forgiven (ნაპატიები) credits with
  repayments; admin-only forgiveness with confirmation.
- **History** — date-range browsing with a summary card (sales count, gross sales,
  received-from-sales, repaid credits, new credits, total cash in till), category
  breakdown, surname search, and admin inline edit/delete.
- **Excel export** — one-click `.xlsx` of the selected period: summary metrics +
  category breakdown + raw transactions in a single sheet.
- **Products, cash, dashboards & reports** — price management, cash view, and
  reporting tabs.
- **Theming** — runtime palette presets + custom colors, saved per user.
- **PIN login** — per-user 4-digit PIN with role-based access (admin / employee).

## Tech stack

- **Python 3.11+**
- **Flet** — cross-platform desktop UI (Windows / macOS)
- **SQLModel + SQLite** — local offline database
- **openpyxl** — Excel export
- **uv** — package manager · **Ruff** — lint/format

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
# install dependencies into a local virtual environment (./venv)
UV_PROJECT_ENVIRONMENT=venv uv sync

# run the app
UV_PROJECT_ENVIRONMENT=venv uv run kodak
```

## Data & configuration

- **Database**: a single SQLite file. By default it lives under the per-machine config
  dir (`%APPDATA%\Kodak` on Windows, `~/Library/Application Support/Kodak` on macOS).
  In a source checkout it uses `./data/kodak.db`. Admins can repoint the DB folder
  (e.g. to a Google-Drive-synced folder) from **Settings**.
- **Session lock**: a `kodak.db.lock` file beside the DB warns if a second machine
  opens the same database, guarding against concurrent-write corruption over cloud sync.
- **Backups**: manual + automatic SQLite snapshots to a configurable folder, plus
  restore-from-backup — all in **Settings**.

## Project layout

```
Kodak/
├── pyproject.toml              # project metadata + deps + [tool.flet] build config
├── src/kodak/
│   ├── main.py                 # Flet entry point + session-lock/backup wiring
│   ├── db.py                   # SQLite + SQLModel session, DB-path resolution
│   ├── config.py               # per-machine JSON config
│   ├── session_lock.py         # cross-machine single-session guard
│   ├── backup.py               # manual/auto backup + restore
│   ├── models/                 # SQLModel schemas
│   ├── services/               # business logic (incl. export.py = Excel)
│   ├── ui/                     # Flet views and components
│   └── assets/icon.png         # app icon (Kodak K-badge), read by flet build
├── tools/make_icon.py          # regenerates the icon (Pillow, dev-only)
├── installer/kodak.iss         # Inno Setup script (Windows installer)
└── .github/workflows/          # CI: build-windows.yml
```

## Building distributables

The app bundles a Python runtime + all dependencies, so end users install nothing.

### Windows (via GitHub Actions)

A Windows `.exe` **cannot be built on macOS** — `flet build windows` requires Windows +
Flutter + Visual Studio (C++ workload). The build therefore runs on a Windows CI runner:

1. **Actions → Build Windows → Run workflow** (or push a tag like `v1.0.0`).
2. Download the `Kodak-Setup-x.y.z.exe` artifact and run it on Windows 10/11.

The workflow runs `flet build windows`, then wraps the output in an Inno Setup installer.
The installer is unsigned, so the first launch shows a SmartScreen prompt
(**More info → Run anyway**).

### macOS (local)

```bash
UV_PROJECT_ENVIRONMENT=venv uv run flet build macos
```

Output: `build/macos/`. (Requires Xcode + Flutter; see `flet build` docs.)
