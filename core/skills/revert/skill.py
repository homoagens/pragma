# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import checkpoint


def revert(path: str = "", list_only: bool = False) -> str:
    """
    [D] Undo file edits made during this session. No LLM involved.

    Every file is copied aside automatically the first time this session
    modifies it, so this restores it to how it was BEFORE the session — not
    before the last of several edits. Files the session created are deleted.

    path      : one file to restore; empty restores everything changed
    list_only : just report what could be restored, change nothing

    Use it when an edit went wrong and rebuilding by hand would be guesswork.
    It cannot undo anything outside the workspace, nor the effects of commands
    run through execute_command.
    """
    entries = checkpoint.list_entries()
    if list_only or not entries:
        if not entries:
            return ("(no file has been modified in this session, so there is "
                    "nothing to revert)")
        lines = [f"{len(entries)} file(s) can be restored to their "
                 f"pre-session state:"]
        for rel, existed in entries:
            lines.append(f"  {rel}" + ("" if existed else "  (created this session — revert deletes it)"))
        lines.append("Call revert() to restore all, or revert(path=...) for one.")
        return "\n".join(lines)

    restored, failed = checkpoint.restore(path)
    out = []
    if restored:
        out.append(f"RESTORED {len(restored)} file(s):")
        out += [f"  {r}" for r in restored]
    if failed:
        out.append(f"FAILED on {len(failed)}:")
        out += [f"  {f}" for f in failed]
    return "\n".join(out) if out else "(nothing to restore)"
