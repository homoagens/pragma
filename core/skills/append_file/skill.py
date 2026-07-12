# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path


def append_file(path: str, content: str, encoding: str = "utf-8",
                ensure_newline: bool = True) -> str:
    """
    [D] Append `content` to the end of a file. No LLM involved — no token risk.

    path           : file to append to (must exist)
    content        : text to append
    encoding       : file encoding (default utf-8)
    ensure_newline : if True and the file doesn't already end with '\\n',
                     a newline is added before `content`
    Returns        : "OK: appended N bytes to <path>" or "ERROR: ..."
    """
    p = Path(path)

    # ── Self-integrity guard: never write into Pragma's own source ──
    import config as _cfg_guard
    _guard = _cfg_guard.self_modify_guard(path)
    if _guard:
        return _guard

    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"

    try:
        existing = p.read_text(encoding=encoding)
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    prefix = ""
    if ensure_newline and existing and not existing.endswith("\n"):
        prefix = "\n"

    try:
        with p.open("a", encoding=encoding) as f:
            if prefix:
                f.write(prefix)
            f.write(content)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    return f"OK: appended {len(content)} bytes to {path}"
