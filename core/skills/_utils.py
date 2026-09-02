# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from datetime import datetime, timezone
try:                      # core/ is normally on sys.path directly
    import clock
except ImportError:       # imported as a package instead
    from core import clock


def _now() -> str:
    return clock.stamp()


# Directories that are never the answer to a code search: dependencies, build
# output, caches, VCS internals. Without skipping these, a search from a
# project root walks the virtualenv and returns library internals instead of
# the project's own code — measured on this repo at 28s and 92% noise for
# grep_search, 97% for glob_match. Shared so both apply the same rule.
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "venv", ".venv", "env", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode",
    ".gradle", "vendor", "site-packages", ".terraform",
    # Pragma's own undo snapshots: searching them would return stale copies of
    # the very files the agent is editing.
    ".pragma_checkpoints",
})
