# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path


def glob_match(pattern: str, base_path: str = ".") -> str:
    """
    Find files matching a glob pattern (supports **).
    Example: pattern="**/*.py", base_path="src"
    Returns a list of relative paths separated by newlines.
    """
    base = Path(base_path)
    if not base.exists():
        return f"ERROR: base_path not found: {base_path}"
    try:
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"(no matches for pattern '{pattern}' in '{base_path}')"
        return "\n".join(m.relative_to(base).as_posix() for m in matches)
    except Exception as e:
        return f"ERROR in glob_match: {e}"
