# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path


def insert_after(path: str, anchor: str, content: str,
                 encoding: str = "utf-8") -> str:
    """
    [D] Deterministic insert: place `content` right after the first occurrence
    of `anchor` in the file. No LLM involved — no token risk.

    path    : file to modify
    anchor  : exact substring to anchor the insertion (must exist verbatim)
    content : text to insert immediately after the anchor
    Returns : "OK: inserted N bytes after anchor in <path>" or "ERROR: ..."
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

    cut = idx + len(anchor)

    # ── Refuse anchors that end in the MIDDLE of a line ──
    # Inserting there would split the line: its tail would end up stranded
    # AFTER the inserted block (field incident: an anchor ending at
    # `if __name__` left ` == '__main__':` dangling below the new function,
    # breaking the file with a SyntaxError). No guessing of intent — the
    # model must re-anchor at a line boundary, which is deterministic.
    if cut < len(text) and text[cut - 1] != "\n":
        nl = text.find("\n", cut)
        tail = text[cut:] if nl < 0 else text[cut:nl]
        if tail:
            return (
                f"ERROR: anchor ends in the MIDDLE of a line — inserting "
                f"here would split it, stranding the rest of the line "
                f"({tail[:60]!r}) below the inserted content and likely "
                f"breaking the file.\n"
                f"Fix: end the anchor at a line boundary — include the "
                f"whole final line, or end the anchor with a newline. For "
                f"an INLINE insertion use replace_in_file instead."
            )

    # Anchor ends at a line boundary (with or without the newline itself).
    sep = "" if cut == len(text) or text[cut - 1] == "\n" else "\n"
    new_text = text[:cut] + sep + content + text[cut:]

    try:
        p.write_text(new_text, encoding=encoding)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    return f"OK: inserted {len(content)} bytes after anchor in {path}"
