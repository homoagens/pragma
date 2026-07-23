# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import subprocess
from pathlib import Path

_TIMEOUT = 30
_MAX_CHARS = 30_000


def git_diff(path: str = ".", staged: bool = False, file: str = "",
             context_lines: int = 3, max_chars: int = 0) -> str:
    """
    Show what actually changed in the working tree, as a unified diff.
    staged : True to show the staged diff instead of the unstaged one.
    file   : limit the diff to one path.
    READ-ONLY: this never stages, commits or reverts anything.

    Use it before concluding, to check that the edits made are the edits
    intended — a diff is the only view that shows what changed rather than
    what a file now contains.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: path not found: {path}"
    cwd = str(p if p.is_dir() else p.parent)

    args = ["diff", f"-U{max(0, context_lines)}"]
    if staged:
        args.append("--cached")
    if file:
        args += ["--", file]

    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=_TIMEOUT)
    except FileNotFoundError:
        return "ERROR: git is not installed or not on PATH"
    except Exception as e:
        return f"ERROR running git diff: {e}"

    if r.returncode != 0:
        return f"ERROR: {(r.stderr or '').strip()[:300]}"

    out = r.stdout or ""
    if not out.strip():
        which = "staged" if staged else "unstaged"
        return (f"(no {which} changes"
                + (f" in {file}" if file else "")
                + ") — try staged=True, or git_status for the overall state")

    limit = max_chars if max_chars > 0 else _MAX_CHARS
    if len(out) > limit:
        head = out[:limit]
        cut = head.rfind("\n")
        if cut > limit // 2:
            head = head[:cut]
        return (f"{head}\n\n... TRUNCATED ({len(head):,} of {len(out):,} chars). "
                f"Pass file=... to diff one path at a time.")
    return out
