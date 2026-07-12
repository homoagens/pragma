# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import os
import re
import subprocess
import sys

# PRAGMA.md (the user-authored project contract) is read-only for the agent.
# The file-mutating skills enforce that via config.self_modify_guard, but the
# shell would happily `del` it — this pattern closes that hole for the common
# destructive verbs and for output redirection onto the file. Known limit:
# it matches the literal name, so wildcard commands (`del *.md`) can still
# slip through — the system prompt rule remains the semantic safety net.
_PRAGMA_MD_SHELL_DENY = re.compile(
    r"\b(del|erase|rd|rmdir|rm|remove-item|ri|move|mv|ren|rename|"
    r"copy|xcopy|robocopy|cp)\b[^&|;]*pragma\.md"
    r"|>\s*\"?[^>|&;\"]*pragma\.md",
    re.IGNORECASE,
)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and ALL its descendants. Survives shell=True on Windows
    (where Popen.kill() only kills cmd.exe, leaving the actual child orphaned)
    and POSIX (where the shell may have spawned a process group)."""
    if proc.poll() is not None:
        return  # already exited
    pid = proc.pid
    try:
        if sys.platform == "win32":
            # /T = tree (all descendants), /F = force
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:
        # Last-resort fallback — kills only the direct child
        try: proc.kill()
        except Exception: pass


def execute_command(command: str, cwd: str = "", timeout: int = 60,
                    capture_stderr: bool = True,
                    max_output_chars: int = 10_000,
                    stop_event=None) -> str:
    """
    Execute a shell command. Captures stdout, stderr, returncode.
    Returns a formatted string with all three values.
    cwd             : working directory (default: current cwd)
    max_output_chars: truncates stdout and stderr if too long (default 10k chars)

    Timeout is enforced by killing the ENTIRE process tree (not just the shell)
    so a hanging child — e.g. a pygame loop, an `input()` call, a server — cannot
    survive past `timeout` seconds.

    CROSS-PLATFORM NOTE: shell=True uses cmd.exe on Windows and /bin/sh on Linux.
    Commands must be written for the target platform.
    Portable commands: echo, cd, python, pip, git.
    Not portable: ls (Linux) vs dir (Windows), cat vs type, etc.
    """
    # ── PRAGMA.md shell guard (see pattern above) ──
    if _PRAGMA_MD_SHELL_DENY.search(command or ""):
        return (
            "ERROR: refused — this shell command would delete, move, rename "
            "or overwrite a PRAGMA.md project-instructions file. PRAGMA.md "
            "is authored by the USER and is read-only for the agent (the "
            "same rule the file-mutating skills enforce). If it should "
            "change or be removed, tell the user to do it themselves. This "
            "is a hard guard — do not retry or work around it."
        )

    work_dir = cwd if cwd else None

    # Spawn in a new process group / job so we can kill the whole tree.
    popen_kwargs: dict = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=work_dir,
    )
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True  # detaches the shell + children

    try:
        proc = subprocess.Popen(command, **popen_kwargs)
    except Exception as e:
        return f"ERROR: {e}"

    timed_out = False
    stopped   = False
    out, err  = "", ""
    try:
        if stop_event is not None:
            # Poll communicate() in slices so we can react to stop_event mid-run
            elapsed = 0.0
            poll    = 0.25
            while True:
                if stop_event.is_set():
                    stopped = True
                    _kill_process_tree(proc)
                    try: out, err = proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired: out, err = "", ""
                    break
                try:
                    out, err = proc.communicate(timeout=poll)
                    break
                except subprocess.TimeoutExpired:
                    elapsed += poll
                    if elapsed >= timeout:
                        timed_out = True
                        _kill_process_tree(proc)
                        try: out, err = proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired: out, err = "", ""
                        break
        else:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_tree(proc)
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc)
                    try: out, err = proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired: out, err = "", ""
    except Exception as e:
        _kill_process_tree(proc)
        return f"ERROR: {e}"

    out = (out or "").strip()
    err = (err or "").strip()

    if len(out) > max_output_chars:
        out = out[:max_output_chars] + f"\n... (truncated at {max_output_chars} chars)"
    if len(err) > max_output_chars:
        err = err[:max_output_chars] + f"\n... (truncated at {max_output_chars} chars)"

    if stopped:
        parts = ["INTERRUPTED: command killed by stop signal — process tree was terminated."]
        if out: parts.append(f"stdout (partial):\n{out}")
        if err and capture_stderr: parts.append(f"stderr (partial):\n{err}")
        return "\n".join(parts)

    if timed_out:
        parts = [
            f"ERROR: command timed out after {timeout}s — process tree was killed.",
            "Possible causes: the script is waiting for user input (input()), "
            "an infinite loop, a GUI window (pygame/tkinter), or a long-running operation. "
            "If the script uses input(), remove it and use hardcoded test values instead.",
        ]
        if out: parts.append(f"stdout (partial):\n{out}")
        if err and capture_stderr: parts.append(f"stderr (partial):\n{err}")
        return "\n".join(parts)

    rc = proc.returncode
    parts = [f"returncode: {rc}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err and capture_stderr:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)
