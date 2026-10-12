# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import subprocess
from pathlib import Path

_TIMEOUT = 20


def _git(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=_TIMEOUT)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "git is not installed or not on PATH"
    except Exception as e:
        return 1, str(e)


def git_status(path: str = ".", max_files: int = 60) -> str:
    """
    Show the state of the git repository: branch, upstream position, and which
    files are staged, modified or untracked.
    READ-ONLY: this never stages, commits, pushes or discards anything.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: path not found: {path}"
    cwd = str(p if p.is_dir() else p.parent)

    code, out = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    if code != 0:
        return f"ERROR: not a git repository (or git unavailable): {out.strip()[:200]}"

    lines: list[str] = []

    _, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    lines.append(f"branch   : {branch.strip()}")

    code, ahead = _git(["rev-list", "--left-right", "--count", "@{upstream}...HEAD"], cwd)
    if code == 0 and ahead.strip():
        parts = ahead.split()
        if len(parts) == 2:
            lines.append(f"upstream : behind {parts[0]}, ahead {parts[1]}")
    else:
        lines.append("upstream : (none configured)")

    code, porcelain = _git(["status", "--porcelain=v1"], cwd)
    entries = [ln for ln in porcelain.splitlines() if ln.strip()]
    if not entries:
        lines.append("state    : clean, nothing to commit")
    else:
        staged = [e for e in entries if e[0] not in " ?"]
        unstaged = [e for e in entries if len(e) > 1 and e[1] != " " and e[0] != "?"]
        untracked = [e for e in entries if e.startswith("??")]
        lines.append(f"state    : {len(staged)} staged, {len(unstaged)} modified, "
                     f"{len(untracked)} untracked")
        lines.append("")
        for e in entries[:max_files]:
            lines.append(f"  {e}")
        if len(entries) > max_files:
            lines.append(f"  ... ({len(entries) - max_files} more)")

    _, log = _git(["log", "--oneline", "-5"], cwd)
    if log.strip():
        lines.append("")
        lines.append("recent commits:")
        for ln in log.splitlines()[:5]:
            lines.append(f"  {ln}")

    return "\n".join(lines)
