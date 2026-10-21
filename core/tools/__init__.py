# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# tools/__init__.py
from __future__ import annotations
import importlib.util
import os
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

# Skills a Unix shell already does, and does better - so on a Unix system they
# are not offered at all.
#
# NOT because they are bad. Because a tool that is offered is a tool that gets
# used: the prompt has said "the shell is a first-class tool here" for a while
# and the model kept reaching for grep_search, which is the cheaper thought.
# A policy written in prose loses to a palette every time, so the palette has
# to agree with it. `grep -rn`, `find`, `sed -n`, `git status`, `ls` answer in
# one call what these answered in five, and they compose - which is the thing
# no fixed signature can offer.
#
# What is NOT in this list, and why. Everything that writes stays, because
# `revert` is a snapshot taken by the dispatcher before a skill that names a
# `path` runs, and execute_command never passes through it: an edit made with
# `sed -i` cannot be undone. file_outline stays because `cat` on a file that
# turns out to be four thousand lines costs the context the outline saves.
#
# On Windows the whole palette stays: cmd.exe has no grep, no usable find, no
# wc, and the prompt there says the opposite for the same reason.
_SHELL_DOES_THIS_BETTER = ("read_file", "list_dir", "glob_match",
                           "grep_search", "git_status", "git_diff")


def palette() -> dict:
    """The skills offered to the agent: everything in the registry but the
    memory machinery (_NOT_AGENT_TOOLS). On a Unix system the shell-replaceable
    half goes too: see _SHELL_DOES_THIS_BETTER. And what only a conversation
    can do is left to the conversation to put back: see _CONVERSATION_ONLY.
    """
    out = dict(ALL_SKILLS)
    for name in _NOT_AGENT_TOOLS + _CONVERSATION_ONLY:
        out.pop(name, None)
    if os.name != "nt":
        for name in _SHELL_DOES_THIS_BETTER:
            out.pop(name, None)
    return out


__all__ = ["ALL_SKILLS", "palette"]
