"""Flet build/run entry point.

`flet build` (and `flet run`) look for a top-level ``main.py`` at the root of
the app directory — which is ``src/`` per ``[tool.flet.app] path``. Flet does
not support dotted module names, so this thin shim lives at ``src/main.py`` to
satisfy the default entry discovery while the real application stays in the
``kodak`` package (with its ``from kodak.… import`` absolute imports).
"""

from __future__ import annotations

import flet as ft

from kodak.main import main

ft.run(main)
