# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# Directories that are never the answer to a code search: dependencies, build
# output, caches, VCS internals. Without skipping these, a search from a
# project root walks the virtualenv and returns library internals instead of
# the project's own code — measured on this repo at 28s and 92% noise for a
# search that walked everything. replace_in_files skips them.
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "venv", ".venv", "env", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode",
    ".gradle", "vendor", "site-packages", ".terraform",
    # Pragma's own undo snapshots: searching them would return stale copies of
    # the very files the agent is editing.
    ".pragma_checkpoints",
})


# An edit that leaves the file exactly as it was is not an edit: answered OK,
# a model that could not see why its change was not taking made the same
# no-op nine times in a row, and nothing that watches for failures saw it.
def unchanged(path) -> str:
    """The refusal for an edit whose result is the file as it already was."""
    return (f"ERROR: nothing changed: {path} would be exactly as it already is. "
            "The text you meant may already be there, or the new text may be the "
            "same as the old: look at the lines again before trying another edit.")
