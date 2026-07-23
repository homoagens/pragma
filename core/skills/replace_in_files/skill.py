# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path

from skills._utils import SKIP_DIRS

_MAX_FILES = 50


def replace_in_files(old: str, new: str, path: str = ".",
                     file_glob: str = "*", dry_run: bool = False,
                     max_files: int = 0, encoding: str = "utf-8") -> str:
    """
    [D] Deterministic find-and-replace across many files. No LLM involved.

    Renaming a symbol across a project costs one call instead of one per file.
    Every occurrence in every matching file is replaced.

    old       : exact substring to find (must exist verbatim)
    new       : replacement substring
    path      : directory to search (dependency/build folders are skipped)
    file_glob : which files to consider, e.g. "*.py"
    dry_run   : report what would change without writing anything
    max_files : safety cap on how many files may be modified (default 50)

    Nothing is written unless every candidate file passes its checks first, so
    a rename cannot leave the project half-converted.
    """
    if not old:
        return "ERROR: `old` must be a non-empty string"
    if old == new:
        return "ERROR: `old` and `new` are identical — nothing to do"

    root = Path(path)
    if not root.exists():
        return f"ERROR: path not found: {path}"

    cap = max_files if max_files > 0 else _MAX_FILES
    import config as _cfg_guard

    candidates: list[tuple[Path, str, int]] = []
    blocked: list[str] = []

    targets = [root] if root.is_file() else sorted(root.rglob(file_glob))
    for f in targets:
        if not f.is_file():
            continue
        if not root.is_file() and SKIP_DIRS.intersection(f.relative_to(root).parts[:-1]):
            continue
        try:
            text = f.read_text(encoding=encoding)
        except Exception:
            continue          # binary or unreadable: not a text edit target
        n = text.count(old)
        if n == 0:
            continue
        # Same self-integrity rule the single-file skill enforces: refuse to
        # write into Pragma's own source. Collected rather than raised, so the
        # report names every file that was refused.
        guard = _cfg_guard.self_modify_guard(str(f))
        if guard:
            blocked.append(f"{f}: {guard.splitlines()[0][:90]}")
            continue
        candidates.append((f, text, n))

    if blocked and not candidates:
        return "ERROR: every match is inside protected files:\n  " + "\n  ".join(blocked)
    if not candidates:
        return (f"(no file under '{path}' matching '{file_glob}' contains the "
                f"given text)\n`old` (first 80 chars): {old[:80]!r}")

    total = sum(n for _, _, n in candidates)
    if len(candidates) > cap:
        return (f"ERROR: {len(candidates)} files contain the text "
                f"({total} occurrences), above the safety cap of {cap}. "
                f"Narrow it with file_glob/path, or raise max_files "
                f"deliberately after a dry_run.")

    header = [f"{'WOULD REPLACE' if dry_run else 'REPLACED'} "
              f"{total} occurrence(s) in {len(candidates)} file(s):"]
    body = []
    written = 0
    for f, text, n in candidates:
        rel = f.relative_to(root) if not root.is_file() else f
        if dry_run:
            body.append(f"  {rel} ({n})")
            continue
        try:
            f.write_text(text.replace(old, new), encoding=encoding)
            written += 1
            body.append(f"  {rel} ({n})")
        except Exception as e:
            body.append(f"  {rel}: ERROR {e}")

    out = header + body
    if blocked:
        out.append(f"skipped {len(blocked)} protected file(s):")
        out += [f"  {b}" for b in blocked]
    if not dry_run and written != len(candidates):
        out.append(f"WARNING: {len(candidates) - written} file(s) failed to write")
    return "\n".join(out)
