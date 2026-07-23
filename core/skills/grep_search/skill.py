# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from skills._utils import SKIP_DIRS

_RG_TIMEOUT = 60


def _find_rg() -> str | None:
    """ripgrep, preferring the one shipped in this environment.

    Installed via the `ripgrep` wheel (see requirements.txt), so it lands next
    to the interpreter rather than on the system PATH.
    """
    local = Path(sys.executable).parent / ("rg.exe" if sys.platform == "win32" else "rg")
    if local.is_file():
        return str(local)
    return shutil.which("rg")


def _search_with_rg(rg: str, pattern: str, path: str, file_glob: str,
                    ignore_case: bool, max_results: int) -> str | None:
    """Run ripgrep. Returns the formatted output, or None to fall back.

    ripgrep honours .gitignore, skips binaries and searches in parallel, so it
    is both faster and quieter than walking the tree ourselves.
    """
    cmd = [rg, "--line-number", "--no-heading", "--color", "never",
           "--max-count", str(max_results)]
    if ignore_case:
        cmd.append("--ignore-case")
    if file_glob and file_glob != "*":
        cmd += ["--glob", file_glob]
    for d in sorted(SKIP_DIRS):
        cmd += ["--glob", f"!{d}/"]
    cmd += ["--regexp", pattern, path]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=_RG_TIMEOUT)
    except Exception:
        return None
    # 0 = matches, 1 = no matches, 2 = error (bad regex, unreadable path).
    if r.returncode not in (0, 1):
        return None

    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return f"(no matches for '{pattern}' in '{path}')"
    truncated = len(lines) > max_results
    lines = lines[:max_results]
    # rg prints "path:lineno:content"; normalise to the ": " form this skill
    # has always returned, so callers and prompts see no difference.
    out = []
    for ln in lines:
        parts = ln.split(":", 2)
        out.append(f"{parts[0]}:{parts[1]}: {parts[2].strip()}"
                   if len(parts) == 3 else ln)
    if truncated:
        out.append(f"... (truncated at {max_results} results)")
    return "\n".join(out)


def _search_with_python(pattern: str, path: str, file_glob: str,
                        ignore_case: bool, max_results: int) -> str:
    """Portable fallback when ripgrep is unavailable. Applies the same
    directory exclusions, so it is usable on a real project even though it
    stays markedly slower than ripgrep."""
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"ERROR: invalid regex '{pattern}': {e}"

    target = Path(path)
    results: list[str] = []
    is_file = target.is_file()
    files = [target] if is_file else sorted(target.rglob(file_glob))

    for f in files:
        if not f.is_file():
            continue
        if not is_file and SKIP_DIRS.intersection(f.relative_to(target).parts[:-1]):
            continue
        display = str(f) if is_file else f.relative_to(target).as_posix()
        try:
            for lineno, line in enumerate(
                    f.read_text(errors="replace").splitlines(), 1):
                if regex.search(line):
                    results.append(f"{display}:{lineno}: {line.rstrip()}")
                    if len(results) >= max_results:
                        results.append(f"... (truncated at {max_results} results)")
                        return "\n".join(results)
        except Exception:
            continue

    if not results:
        return f"(no matches for '{pattern}' in '{path}')"
    return "\n".join(results)


def grep_search(pattern: str, path: str = ".", file_glob: str = "*",
                ignore_case: bool = False, max_results: int = 100) -> str:
    """
    Search a regex pattern in file contents.
    path      : directory or single file
    file_glob : filter files (e.g. "*.py", "*.md")
    Dependencies, build output and VCS folders are skipped; .gitignore is
    honoured when ripgrep is available.
    Returns matches in the format "path:lineno: line_content".
    """
    if not Path(path).exists():
        return f"ERROR: path not found: {path}"

    rg = _find_rg()
    if rg:
        out = _search_with_rg(rg, pattern, path, file_glob,
                              ignore_case, max_results)
        if out is not None:
            return out
    return _search_with_python(pattern, path, file_glob,
                               ignore_case, max_results)
