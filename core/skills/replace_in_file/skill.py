from __future__ import annotations

from pathlib import Path


def replace_in_file(path: str, old: str, new: str, count: int = 1,
                    encoding: str = "utf-8") -> str:
    """
    [D] Deterministic find-and-replace in a file. No LLM involved.

    path     : file to modify
    old      : exact substring to find (must exist verbatim)
    new      : replacement substring
    count    : how many occurrences to replace (default 1; use -1 for all)
    encoding : file encoding
    Returns  : "OK: replaced N occurrence(s) in <path>" or "ERROR: ..."
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
    if not old:
        return "ERROR: `old` must be a non-empty string"

    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    occurrences = text.count(old)
    if occurrences == 0:
        return (
            f"ERROR: substring not found in {path}.\n"
            f"`old` (first 80 chars): {old[:80]!r}"
        )

    if count == -1:
        new_text = text.replace(old, new)
        replaced = occurrences
    else:
        new_text = text.replace(old, new, count)
        replaced = min(count, occurrences)

    try:
        p.write_text(new_text, encoding=encoding)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    return f"OK: replaced {replaced} occurrence(s) in {path}"
