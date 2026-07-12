# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path


def read_file(path: str, encoding: str = "utf-8",
              start_line: int = 0, end_line: int = 0) -> str:
    """
    Read the contents of a file.
    start_line / end_line: if both > 0, return only those lines (1-based).
    Returns the content as a string, or an error message.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"
    if start_line > 0 and end_line > 0 and start_line > end_line:
        return f"ERROR: start_line ({start_line}) must be <= end_line ({end_line})"
    try:
        text = p.read_text(encoding=encoding)
        if start_line > 0 and end_line > 0:
            lines = text.splitlines()
            selected = lines[start_line - 1: end_line]
            return "\n".join(selected)
        return text
    except Exception as e:
        return f"ERROR reading {path}: {e}"
