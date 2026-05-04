from __future__ import annotations

import os
import sys
from pathlib import Path


def understand_cwd(max_depth: int = 2) -> str:
    """
    Builds an operational map of the current environment:
    cwd, Python version, platform, selected env variables (whitelist),
    directory structure (up to max_depth levels, excluding noisy folders).
    """
    cwd = Path.cwd()

    # Whitelist: only vars with operational meaning for an agent.
    # Covers Windows, Linux and macOS. Everything else is counted but not shown.
    _useful = {
        # Machine and user identity
        "COMPUTERNAME", "HOSTNAME",                         # Windows / Linux+macOS
        "USERNAME", "USER",                                 # Windows / Linux+macOS
        "USERPROFILE", "HOME",                              # Windows / Linux+macOS
        "HOMEPATH", "HOMEDRIVE",                            # Windows only
        "LOGONSERVER", "SESSIONNAME",                       # Windows only
        # Operating system
        "OS", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",        # Windows only
        # Temporary directory
        "TEMP", "TMP", "TMPDIR",                            # Win / Linux+macOS
        # Shell and terminal
        "SHELL", "TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM",
        # Locale
        "LANG", "LC_ALL", "LC_CTYPE",
        # Hardware
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",   # Windows
        # Python environments
        "CONDA_DEFAULT_ENV", "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT",
        # Miscellaneous
        "PWD",                                              # Linux+macOS
    }
    shown_env  = {k: v for k, v in os.environ.items() if k in _useful}
    hidden_cnt = len(os.environ) - len(shown_env)

    # Folders to hide entirely from the tree
    _hide = {"venv", ".venv", "__pycache__", ".git",
             "node_modules", "dist", "build", ".tox", ".mypy_cache",
             ".pytest_cache", "*.egg-info"}

    def _tree(p: Path, depth: int, prefix: str = "") -> list[str]:
        if depth == 0:
            return []
        rows = []
        try:
            children = sorted(p.iterdir())
        except PermissionError:
            return [f"{prefix}[permission denied]"]
        visible = [
            c for c in children
            if c.name not in _hide
            and not c.name.endswith(".egg-info")
            and (not c.name.startswith(".") or c.name == ".env")
        ]
        for child in visible[:30]:
            connector = "dir" if child.is_dir() else "   "
            rows.append(f"{prefix}[{connector}] {child.name}")
            if child.is_dir() and depth > 1:
                rows.extend(_tree(child, depth - 1, prefix + "    "))
        if len(visible) > 30:
            rows.append(f"{prefix}... ({len(visible) - 30} more)")
        return rows

    tree_lines = _tree(cwd, max_depth)
    env_lines  = [f"  {k}={v}" for k, v in sorted(shown_env.items())]

    return "\n".join([
        f"cwd      : {cwd}",
        f"python   : {sys.version.split()[0]}  ({sys.executable})",
        f"platform : {sys.platform}",
        "",
        "directory structure:",
        *tree_lines,
        "",
        f"environment ({len(shown_env)} shown, {hidden_cnt} hidden):",
        *env_lines,
    ])
