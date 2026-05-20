from __future__ import annotations

import base64
from pathlib import Path


def replace_in_file_b64(path: str,
                        old_b64: str,
                        new_b64: str,
                        count: int = 1,
                        encoding: str = "utf-8") -> str:
    """
    [D] Find-and-replace where `old` and `new` arrive base64-encoded.

    Why this skill exists
    ---------------------
    The normal `replace_in_file` requires the agent to pass `old` and `new`
    as plain JSON strings. That's fine 99 % of the time, but breaks when
    either side contains escape-sensitive byte sequences — most notably
    when a FILE contains LITERAL `\\n` (two characters: backslash + n)
    instead of a real newline. To match that with normal `replace_in_file`
    the model has to:
      * write `\\\\n` in the JSON action so the JSON parser yields `\\n`,
      * AND remember to use a DIFFERENT escape level for `new` if it wants
        a real newline there.
    Small models (and even big ones under pressure) routinely get this
    double-escape wrong and end up in a fix-fail-fix-fail loop.

    Base64 sidesteps the entire JSON-escape layer: only ASCII letters,
    digits, `+`, `/`, `=` cross the wire, no special characters whatsoever.
    The model encodes the exact bytes it wants, the skill decodes them
    back to bytes and does a literal substring replacement.

    Parameters
    ----------
    path     : file to modify
    old_b64  : base64 of the exact bytes to find (must exist verbatim
               in the file)
    new_b64  : base64 of the replacement bytes
    count    : how many occurrences to replace (default 1; -1 = all)
    encoding : file encoding for reading/writing (default utf-8)

    Returns
    -------
    "OK: replaced N occurrence(s) in <path>"  on success,
    "ERROR: ..."                              on any failure (file missing,
    invalid base64, substring not found, write failure).
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
    if not old_b64:
        return "ERROR: `old_b64` must be a non-empty base64 string"

    # Decode the two payloads. Treat the result as TEXT (caller's encoding).
    # If the bytes don't decode cleanly with the requested encoding we
    # surface the error rather than corrupting the file.
    try:
        old_bytes = base64.b64decode(old_b64, validate=False)
        new_bytes = base64.b64decode(new_b64, validate=False)
    except Exception as e:
        return f"ERROR: invalid base64 input — {e}"
    try:
        old = old_bytes.decode(encoding)
        new = new_bytes.decode(encoding)
    except UnicodeDecodeError as e:
        return f"ERROR: decoded bytes are not valid {encoding} — {e}"

    if not old:
        return "ERROR: decoded `old` is empty"

    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    occurrences = text.count(old)
    if occurrences == 0:
        # Include a short hint about what the decoded payload looked like
        # so the agent doesn't have to guess what went wrong.
        preview = old.replace("\\", "\\\\").replace("\n", "\\n")[:80]
        return (
            f"ERROR: decoded `old` not found in {path}.\n"
            f"Decoded preview (first 80 chars, escaped): {preview!r}\n"
            f"The base64 round-trip succeeded — the issue is that this exact "
            f"byte sequence does not occur in the file. Re-read the file and "
            f"re-encode the precise substring you want to match."
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
