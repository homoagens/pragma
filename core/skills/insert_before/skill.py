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

    # If the anchor starts mid-line, add a newline after the new content
    # so the inserted block stays on its own lines.
    sep = "" if idx == 0 or text[idx - 1] == "\n" else "\n"
    new_text = text[:idx] + content + sep + text[idx:]

    try:
        p.write_text(new_text, encoding=encoding)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    return f"OK: inserted {len(content)} bytes before anchor in {path}"
