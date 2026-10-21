#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""The colours and the width every Pragma screen draws with.

The accent was read from PRAGMA_ACCENT in five places - the menus, the home
screen, the conversation's prompt, its rich colours, the memory views - each
with its own copy of the same check and the same default; the width of the
terminal in three. One copy each, here, with nothing to import but the
standard library: the conversation and the memory worker load it as readily
as the menus do.
"""
from __future__ import annotations

import os
import shutil
import sys

ESC = "\033"
GREY, RESET = ESC + "[38;5;242m", ESC + "[0m"

# PRAGMA_ACCENT is set by whoever started this, so that a page and the prompt
# drawn under it are the same colour.
DEFAULT_ACCENT = "178;132;255"


def accent_rgb() -> str:
    """PRAGMA_ACCENT as "R;G;B", or the default when it is not one."""
    raw = (os.environ.get("PRAGMA_ACCENT") or DEFAULT_ACCENT).strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        return DEFAULT_ACCENT
    return raw


def accent() -> str:
    """The accent as an ANSI foreground - nothing when the output is not a terminal."""
    return ESC + "[38;2;" + accent_rgb() + "m" if sys.stdout.isatty() else ""


def accent_hex() -> str:
    """The accent as a rich colour."""
    return "#{:02x}{:02x}{:02x}".format(*(int(p) for p in accent_rgb().split(";")))


def columns(least: int = 24, fallback: int = 80) -> int:
    """The terminal's width, never under `least`."""
    try:
        return max(least, shutil.get_terminal_size((fallback, 24)).columns)
    except Exception:
        return fallback
