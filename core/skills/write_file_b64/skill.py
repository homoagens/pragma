# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import base64
from pathlib import Path


def write_file_b64(path: str,
                   content_b64: str,
                   encoding: str = "utf-8",
                   create_parents: bool = True,
                   overwrite: bool = False) -> str:
    """
    [D] Like write_file, but `content` arrives base64-encoded.

    Why this skill exists
    ---------------------
    The normal `write_file` requires the agent to ship the file content as
    a plain JSON string. On long content (~5 KB+) the model's JSON
    compliance often fails: a literal newline, a stray quote, or a mishandled
    escape inside the string breaks the JSON parser. json-repair can recover
    SOME of the dict but typically drops at least one field (commonly
    `path`), making the call useless.

    Base64 sidesteps the entire JSON-escape layer: only `[A-Za-z0-9+/=]`
    characters cross the wire, no special characters whatsoever. The model
    encodes the exact bytes it wants, the skill decodes them, and writes
    the file. Same overwrite / size / parent-creation guards as write_file.

    Parameters
    ----------
    path           : target file path
    content_b64    : base64-encoded bytes of the file content
    encoding       : file encoding for writing (default utf-8)
    create_parents : if True, create intermediate directories
    overwrite      : if True, allow replacing an existing file
                     (matches write_file's semantic exactly)

    Returns
    -------
    "OK: written N bytes to <path>"   on success (warning appended when
    N exceeds WRITE_FILE_SOFT_LIMIT)
    "ERROR: file already exists ..."  when target exists and overwrite=False
    "ERROR: content too large ..."    when the decoded size exceeds
                                      WRITE_FILE_HARD_LIMIT (same cap as
                                      write_file — base64 doesn't bypass
                                      size budgets, only escape ambiguity)
    "ERROR: invalid base64 ..."       when content_b64 fails to decode
    "ERROR writing ..."               on I/O failure
    """
    if not content_b64:
        return "ERROR: `content_b64` must be a non-empty base64 string"

    # ── Self-integrity guard: never write into Pragma's own source ──
    import config as _cfg_guard
    _guard = _cfg_guard.self_modify_guard(path)
    if _guard:
        return _guard

    # Decode base64 → raw bytes → text (in the requested encoding).
    try:
        raw_bytes = base64.b64decode(content_b64, validate=False)
    except Exception as e:
        return f"ERROR: invalid base64 input — {e}"
    try:
        content = raw_bytes.decode(encoding)
    except UnicodeDecodeError as e:
        return f"ERROR: decoded bytes are not valid {encoding} — {e}"

    p = Path(path)

    # ── Refuse to clobber an existing file unless explicitly authorized ──
    # Mirrors write_file's behavior so the two skills are interchangeable
    # at the safety level.
    if p.exists() and not overwrite:
        try:
            current_size = p.stat().st_size
        except Exception:
            current_size = -1
        return (
            f"ERROR: file already exists at {path} "
            f"({current_size} bytes). write_file_b64 is for NEW files only "
            f"unless you pass overwrite=true.\n"
            f"To modify it, use one of:\n"
            f"  - replace_in_file_b64(path, old_b64, new_b64)  exact replace, JSON-safe\n"
            f"  - replace_in_file(path, old, new)              exact replace\n"
            f"  - insert_after / insert_before / append_file\n"
            f"  - edit_file(path, instruction)                 interpret-and-patch\n"
            f"If you truly need to rewrite the whole file from scratch, "
            f"call write_file_b64 again with overwrite=true."
        )

    # ── Refuse single writes larger than the hard limit ──
    # Decoded size, not base64 length. Same threshold as write_file.
    try:
        import config as _cfg
        hard = getattr(_cfg, "WRITE_FILE_HARD_LIMIT", 0)
    except Exception:
        hard = 0
    n_bytes = len(content.encode(encoding))
    if hard > 0 and n_bytes > hard:
        return (
            f"ERROR: content too large ({n_bytes} bytes > hard limit {hard}). "
            f"base64 fixes JSON escape ambiguity but does NOT raise the size "
            f"limit. Build the file incrementally:\n"
            f"  1. write_file_b64 with the SCAFFOLDING only (~1-2 KB).\n"
            f"  2. append_file ONCE PER SECTION (~1 KB each).\n"
            f"  3. (optional) final append_file with closing tags."
        )

    try:
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
    except Exception as e:
        return f"ERROR writing {path}: {e}"

    # Soft size warning — informs the agent that a large write happened
    # so on subsequent edits it prefers edit_file / insert_* / replace_in_file.
    try:
        import config as _cfg2
        soft = getattr(_cfg2, "WRITE_FILE_SOFT_LIMIT", 0)
    except Exception:
        soft = 0
    if soft > 0 and n_bytes > soft:
        return (
            f"OK: written {n_bytes} bytes to {path}\n"
            f"NOTE: large write ({n_bytes} bytes > soft limit {soft}). "
            f"For future changes on this file prefer replace_in_file_b64, "
            f"insert_after, insert_before, append_file or replace_in_file."
        )
    return f"OK: written {n_bytes} bytes to {path}"
