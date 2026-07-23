# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from pathlib import Path

from skills._utils import SKIP_DIRS

_DEFAULT_MAX = 300


def glob_match(pattern: str, base_path: str = ".", max_results: int = 0,
               include_ignored: bool = False) -> str:
    """
    Find files matching a glob pattern (supports **).
    Example: pattern="**/*.py", base_path="src"
    Dependency, build and VCS directories are skipped unless
    include_ignored=True. Returns relative paths, newest-first ordering is not
    applied — results are sorted by path.
    """
    base = Path(base_path)
    if not base.exists():
        return f"ERROR: base_path not found: {base_path}"
    limit = max_results if max_results > 0 else _DEFAULT_MAX
    try:
        matches = []
        skipped = 0
        for m in sorted(base.glob(pattern)):
            rel = m.relative_to(base)
            if not include_ignored and SKIP_DIRS.intersection(rel.parts):
                skipped += 1
                continue
            matches.append(rel.as_posix())

        if not matches:
            extra = (f" ({skipped} match(es) were inside dependency/build "
                     f"folders; pass include_ignored=True to see them)"
                     if skipped else "")
            return f"(no matches for pattern '{pattern}' in '{base_path}'){extra}"

        truncated = len(matches) > limit
        out = matches[:limit]
        if truncated:
            out.append(f"... (truncated at {limit} of {len(matches)} matches)")
        if skipped:
            out.append(f"({skipped} match(es) skipped in dependency/build folders)")
        return "\n".join(out)
    except Exception as e:
        return f"ERROR in glob_match: {e}"
