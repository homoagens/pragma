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
        # _template, _legacy and _future stay in the tree and are never
        # offered: a leading underscore is how a skill is retired.
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
        # Strip wip_ prefix to find the actual function name and registry key.
        # This allows skill folders to be prefixed with wip_ for testing
        # without changing the function name or the agent-visible skill name.
        skill_name = folder.name[len("wip_"):] if folder.name.startswith("wip_") else folder.name
        fn = getattr(mod, skill_name, None)
        if fn is None:
            continue
        registry[skill_name] = fn
    # What the model is told about each skill - its description and its exact
    # parameters - is built from the README and the function by tool_schema.
    return registry


ALL_SKILLS = _load_skills()


# Memory machinery that lives in skills/ for its imports, not for the agent.
# The raw recall skills reinforce and revive on keyword overlap alone, with no
# judgement between the prefilter and the write, so an agent free to call them
# would turn salience into a count of how often a word recurred: memory reaches
# the agent only through the curator. Consolidation and reflection run after a
# task, never as a step inside one. Chat and batch each used to pop the recall
# skills on their own and the browser server did not, so the rule lives here.
_NOT_AGENT_TOOLS = ("recall_episodes", "recall_learnings",
                    "episode_consolidate", "session_reflect")

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


def palette(base: dict | None = None) -> dict:
    """The skills offered to the agent.

    Everything in the registry except the memory machinery: the raw recall
    skills reinforce and revive on keyword overlap alone, with no judgement
    between the prefilter and the write, so an agent free to call them would
    turn salience into a count of how often a word recurred - memory reaches
    the agent only through the curator. Consolidation and reflection run after
    a task, never as a step inside one. Chat and batch each used to pop them
    on their own and the browser server did not, so the rule lives here.

    On a Unix system the shell-replaceable half goes too: see
    _SHELL_DOES_THIS_BETTER. And what only a conversation can do is left to
    the conversation to put back: see _CONVERSATION_ONLY.
    """
    out = dict(ALL_SKILLS if base is None else base)
    for name in _NOT_AGENT_TOOLS + _CONVERSATION_ONLY:
        out.pop(name, None)
    if os.name != "nt":
        for name in _SHELL_DOES_THIS_BETTER:
            out.pop(name, None)
    return out


__all__ = ["ALL_SKILLS", "palette"]
