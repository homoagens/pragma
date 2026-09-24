# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# skills/__init__.py
from __future__ import annotations
import importlib.util
import inspect
import os
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def _format_signature(name: str, fn) -> str:
    """Render an exact `name(param, opt=default, ...)` call signature from the
    skill function itself.

    This goes into the system prompt next to every skill. It is the cheapest
    fix for the most common skill-call failure: the model inventing or
    over-generalizing parameters (e.g. passing `overwrite` to append_file, or
    `output_mode` to grep_search). Showing the precise parameter list — and,
    by omission, which parameters do NOT exist — kills that whole error class.
    Derived from the live function, so it can never go stale.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return f"{name}(...)"
    parts = []
    for p in sig.parameters.values():
        if p.name in ("self", "cls"):
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"*{p.name}")
            continue
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            parts.append(f"**{p.name}")
            continue
        if p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            d = repr(p.default)
            if len(d) > 24:  # keep long string defaults from bloating the prompt
                d = d[:21] + "..."
            parts.append(f"{p.name}={d}")
    return f"{name}({', '.join(parts)})"


def _load_skills():
    registry = {}
    # name -> "**name**: desc\n  Call: sig". Kept per-skill (not pre-joined)
    # so a runner can rebuild the summary for a SUBSET of the palette — see
    # skills_summary_for(). Insertion order follows the sorted folder scan.
    summary_lines = {}
    for folder in sorted(SKILLS_DIR.iterdir()):
        # _template, _legacy and _future stay in the tree and are never
        # offered: a leading underscore is how a skill is retired.
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        skill_file = folder / "skill.py"
        readme = folder / "README.md"
        if not skill_file.exists():
            continue
        mod_name = f"skills.{folder.name}.skill"
        spec = importlib.util.spec_from_file_location(mod_name, skill_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod  # register BEFORE exec so late imports work
        sys.modules[f"skills.{folder.name}"] = mod
        spec.loader.exec_module(mod)
        # Strip wip_ prefix to find the actual function name and registry key.
        # This allows skill folders to be prefixed with wip_ for testing
        # without changing the function name or the agent-visible skill name.
        skill_name = folder.name[len("wip_"):] if folder.name.startswith("wip_") else folder.name
        fn = getattr(mod, skill_name, None)
        if fn is None:
            continue
        registry[skill_name] = fn
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            summary_part = text.split("---")[0].strip()
            # Extract just the description line (after the # title)
            lines = [ln for ln in summary_part.splitlines() if ln.strip() and not ln.startswith("#")]
            summary = lines[0] if lines else summary_part
            # Append the exact call signature on its own line so the model
            # sees the precise parameters every turn, not only after a
            # get_skill_details call.
            sig = _format_signature(skill_name, fn)
            summary_lines[skill_name] = f"**{skill_name}**: {summary}\n  Call: {sig}"
    return registry, summary_lines


ALL_SKILLS, _SUMMARY_LINES = _load_skills()
SKILLS_SUMMARY = "\n".join(_SUMMARY_LINES.values())


def skills_summary_for(names) -> str:
    """Build the skills-summary block for a SUBSET of skills, in the canonical
    order. Use this to keep the system prompt in sync with the ACTUAL palette
    when a runner hides skills from the agent (e.g. the base64 skills on the
    native channel): otherwise the prompt would advertise skills the agent
    cannot call, and the model wastes turns calling them ('skill does not
    exist'). Names without a summary line are
    skipped, exactly as in SKILLS_SUMMARY."""
    wanted = set(names)
    return "\n".join(line for name, line in _SUMMARY_LINES.items()
                     if name in wanted)


# Memory machinery that lives in skills/ for its imports, not for the agent.
# The raw recall skills reinforce and revive on keyword overlap alone, with no
# judgement between the prefilter and the write, so an agent free to call them
# would turn salience into a count of how often a word recurred: memory reaches
# the agent only through the curator. Consolidation and reflection run after a
# task, never as a step inside one. Chat and batch each used to pop the recall
# skills on their own and the browser server did not, so the rule lives here.
_NOT_AGENT_TOOLS = ("recall_episodes", "recall_learnings",
                    "episode_consolidate", "session_reflect")

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
    _SHELL_DOES_THIS_BETTER.
    """
    out = dict(ALL_SKILLS if base is None else base)
    for name in _NOT_AGENT_TOOLS:
        out.pop(name, None)
    if os.name != "nt":
        for name in _SHELL_DOES_THIS_BETTER:
            out.pop(name, None)
    return out


__all__ = ["ALL_SKILLS", "SKILLS_SUMMARY", "skills_summary_for",
           "palette"]
