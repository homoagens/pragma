# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path


def insert_before(path: str, anchor: str, content: str,
                  encoding: str = "utf-8") -> str:
    """
    [D] Deterministic insert: place `content` right before the first occurrence
    of `anchor` in the file. No LLM involved — no token risk.

    path    : file to modify
    anchor  : exact substring to anchor the insertion (must exist verbatim)
    content : text to insert immediately before the anchor
    Returns : "OK: inserted N bytes before anchor in <path>" or "ERROR: ..."
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
    if not anchor:
        return "ERROR: anchor must be a non-empty string"

    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    idx = text.find(anchor)
    if idx < 0:
        return (
            f"ERROR: anchor not found in {path}.\n"
            f"Anchor (first 80 chars): {anchor[:80]!r}\n"
            f"Hint: anchor must be copied verbatim from the file, including whitespace."
        )

    # ── Refuse anchors that start in the MIDDLE of a line ──
    # Symmetric to insert_after's guard: inserting there would split the
    # line, stranding its head ABOVE the inserted block. The model must
    # re-anchor at a line boundary — deterministic, no intent guessing.
    if idx > 0 and text[idx - 1] != "\n":
        ls = text.rfind("\n", 0, idx) + 1  # start of the anchor's line
        head = text[ls:idx]
        if head:
            return (
                f"ERROR: anchor starts in the MIDDLE of a line — inserting "
                f"here would split it, stranding the start of the line "
                f"({head[:60]!r}) above the inserted content and likely "
                f"breaking the file.\n"
                f"Fix: start the anchor at a line boundary — begin with the "
                f"whole line (indentation included). For an INLINE "
                f"insertion use replace_in_file instead."
            )

    # Anchor starts at a line boundary.
    new_text = text[:idx] + content + text[idx:]

    try:
        p.write_text(new_text, encoding=encoding)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    return f"OK: inserted {len(content)} bytes before anchor in {path}"
