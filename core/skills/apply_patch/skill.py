# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import base64
import binascii
import re
import subprocess
import tempfile
from pathlib import Path

_TIMEOUT = 30

# "+++ b/path" (and "--- a/path" for deletions) name the files a diff touches.
_TARGET = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$", re.M)
_SOURCE = re.compile(r"^--- (?:a/)?(.+?)\s*$", re.M)


def _targets(diff: str) -> list[str]:
    out = []
    for m in list(_TARGET.finditer(diff)) + list(_SOURCE.finditer(diff)):
        p = m.group(1).strip()
        if p and p != "/dev/null" and p not in out:
            out.append(p)
    return out


def apply_patch(diff: str = "", cwd: str = "", diff_b64: str = "",
                dry_run: bool = False) -> str:
    """
    [D] Apply a unified diff. No LLM involved.

    One call for a set of coordinated changes — several hunks, several files —
    instead of one call per edit. Unlike a substring replace, a diff carries
    its context lines, so it is applied at the intended place or REFUSED: it
    cannot silently patch the wrong occurrence.

    diff     : the unified diff text (--- / +++ / @@ hunks)
    diff_b64 : the same diff, base64-encoded. PREFER THIS. A diff is multi-line
               and full of quotes and backslashes, exactly the payload that
               breaks the JSON argument layer; base64 is pure ASCII and cannot
               be mangled. Pass either diff or diff_b64, not both.
    cwd      : directory the paths in the diff are relative to
    dry_run  : verify the patch applies cleanly, change nothing

    Paths in the diff are relative to cwd; "a/" and "b/" prefixes are accepted.
    Requires git on PATH (used only as the patch engine — no repository needed,
    nothing is staged or committed).
    """
    if diff and diff_b64:
        return "ERROR: pass either `diff` or `diff_b64`, not both"
    if diff_b64:
        try:
            diff = base64.b64decode(diff_b64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as e:
            return f"ERROR: `diff_b64` is not valid base64-encoded UTF-8: {e}"
    if not diff.strip():
        return "ERROR: empty diff — nothing to apply"

    work = Path(cwd) if cwd else Path.cwd()
    if not work.is_dir():
        return f"ERROR: cwd is not a directory: {work}"

    targets = _targets(diff)
    if not targets:
        return ("ERROR: no file headers found in the diff. A unified diff needs "
                "`--- a/path` and `+++ b/path` lines above each `@@` hunk.")

    # Self-integrity guard: the same rule the file-mutating skills enforce.
    # A patch can reach several files at once, so every target is checked
    # before anything is applied.
    import config as _cfg_guard
    for t in targets:
        blocked = _cfg_guard.self_modify_guard(str(work / t))
        if blocked:
            return (f"ERROR: refused — the patch touches {t}, which is part of "
                    f"Pragma's own source.\n{blocked.splitlines()[0]}")

    # A patch reaches files named only inside the diff, so the runner cannot
    # snapshot them from the call arguments: do it here, before anything is
    # written, so `revert` can undo a patch that turns out wrong.
    if not dry_run:
        try:
            import checkpoint
            for t in targets:
                checkpoint.snapshot(str(work / t))
        except Exception:
            pass

    tmp = None
    try:
        # git apply reads the patch from a file; a temp file also keeps the
        # diff byte-exact, which matters because trailing whitespace is
        # significant in context lines.
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False,
                                         encoding="utf-8", newline="") as fh:
            body = diff if diff.endswith("\n") else diff + "\n"
            fh.write(body)
            tmp = fh.name

        base = ["git", "apply", "--unsafe-paths", f"--directory={work}"]
        check = subprocess.run(base + ["--check", tmp], cwd=str(work),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=_TIMEOUT)
        if check.returncode != 0:
            err = (check.stderr or check.stdout or "").strip()
            return (f"ERROR: the patch does not apply cleanly — nothing was "
                    f"changed.\n{err[:600]}\n"
                    f"The context lines must match the file exactly. Re-read "
                    f"the file and rebuild the diff from its current content.")
        if dry_run:
            return (f"DRY RUN OK: the patch applies cleanly to "
                    f"{len(targets)} file(s): {', '.join(targets)}")

        run = subprocess.run(base + [tmp], cwd=str(work), capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=_TIMEOUT)
        if run.returncode != 0:
            err = (run.stderr or run.stdout or "").strip()
            return f"ERROR applying the patch: {err[:600]}"

        hunks = diff.count("\n@@")+ (1 if diff.startswith("@@") else 0)
        return (f"OK: applied {hunks} hunk(s) across {len(targets)} file(s): "
                f"{', '.join(targets)}")
    except FileNotFoundError:
        return ("ERROR: git is not installed or not on PATH. apply_patch uses "
                "git as its patch engine; use replace_in_file or "
                "replace_in_files instead.")
    except subprocess.TimeoutExpired:
        return f"ERROR: git apply timed out after {_TIMEOUT}s"
    except Exception as e:
        return f"ERROR in apply_patch: {e}"
    finally:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
