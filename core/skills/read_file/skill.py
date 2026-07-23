# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path

# A single unbounded read can fill the whole context window in one turn, and
# the damage is done before any history compaction can help: the model then
# reasons for the rest of the session on a prompt that is mostly one file.
# ~40k characters is roughly 10k tokens — large enough for almost every source
# file, small enough to leave room to think.
_MAX_CHARS = 40_000


def read_file(path: str, encoding: str = "utf-8",
              start_line: int = 0, end_line: int = 0,
              max_chars: int = 0) -> str:
    """
    Read the contents of a file.
    start_line / end_line: if both > 0, return only those lines (1-based).
    max_chars: cap on returned characters (0 = default cap). Oversized reads
    are truncated with a notice rather than flooding the context.
    Returns the content as a string, or an error message.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"
    if start_line > 0 and end_line > 0 and start_line > end_line:
        return f"ERROR: start_line ({start_line}) must be <= end_line ({end_line})"

    limit = max_chars if max_chars > 0 else _MAX_CHARS
    try:
        text = p.read_text(encoding=encoding)
        if start_line > 0 and end_line > 0:
            lines = text.splitlines()
            text = "\n".join(lines[start_line - 1: end_line])

        if len(text) <= limit:
            return text

        # Cut on a line boundary so the tail is never a half-written line the
        # model might treat as real code.
        head = text[:limit]
        cut = head.rfind("\n")
        if cut > limit // 2:
            head = head[:cut]
        shown = head.count("\n") + 1
        total = text.count("\n") + 1
        return (
            f"{head}\n\n"
            f"... TRUNCATED: showed {shown} of {total} lines "
            f"({len(head):,} of {len(text):,} chars).\n"
            f"Read a specific range with start_line/end_line, use file_outline "
            f"for the structure, or grep_search to find what you need."
        )
    except Exception as e:
        return f"ERROR reading {path}: {e}"
