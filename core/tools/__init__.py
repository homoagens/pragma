# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# tools/__init__.py
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def _load_skills():
    registry = {}
    for folder in sorted(SKILLS_DIR.iterdir()):
        # A leading underscore is not a skill: _template is the starting point
        # for a new one.
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        skill_file = folder / "tool.py"
        if not skill_file.exists():
            continue
        mod_name = f"tools.{folder.name}.tool"
        spec = importlib.util.spec_from_file_location(mod_name, skill_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod  # register BEFORE exec so late imports work
        sys.modules[f"tools.{folder.name}"] = mod
        spec.loader.exec_module(mod)
        fn = getattr(mod, folder.name, None)
        if fn is None:
            continue
        registry[folder.name] = fn
    # What the model is told about each skill - its description and its exact
    # parameters - is built from the README and the function by tool_schema.
    return registry


ALL_SKILLS = _load_skills()


# Memory machinery that lives in skills/ for its imports, not for the agent.
# Consolidation runs after a conversation, never as a step inside one, and
# memory reaches the agent only through the curator.
_NOT_AGENT_TOOLS = ("episode_consolidate",)

# Tools for a person watching the terminal as the turn goes. Only a
# conversation has one, and agent/chat.py puts in its own version of each;
# anywhere else they would be offered and do nothing.
_CONVERSATION_ONLY = ("show_image",)

# THE SHELL READS, SEARCHES AND ASKS GIT. There are no skills for reading a
# file, listing a folder, globbing, grepping or asking git: there were, and on
# Linux and macOS they were never offered, because a tool that is offered is a
# tool that gets used and the model kept reaching for them over `grep -rn`,
# `find`, `sed -n`, `git status` and `ls`, which answer in one call what they
# answered in five, and compose. They existed for cmd.exe, which has none of
# that; Pragma runs on Windows inside WSL now.
#
# What stays, and why. Everything that writes, because `revert` is a snapshot
# taken by the dispatcher before a skill that names a `path` runs, and
# execute_command never passes through it: an edit made with `sed -i` cannot
# be undone. file_outline, because `cat` on a file that turns out to be four
# thousand lines costs the context the outline saves.


def palette() -> dict:
    """The skills offered to the agent: everything in the registry but the
    memory machinery (_NOT_AGENT_TOOLS). What only a conversation can do is
    left to the conversation to put back: see _CONVERSATION_ONLY.
    """
    out = dict(ALL_SKILLS)
    for name in _NOT_AGENT_TOOLS + _CONVERSATION_ONLY:
        out.pop(name, None)
    return out


__all__ = ["ALL_SKILLS", "palette"]
