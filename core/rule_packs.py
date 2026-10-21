# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""Rule packs: short sets of rules for a kind of work, turned on by the person.

A pack is one Markdown file. Its first line says what it is for, and the
whole file is what the agent reads. Pragma comes with some, in core/rules/;
a person adds their own in ~/.pragma/rules/, and one there with the same
name takes the place of Pragma's.

WHO DECIDES. The person, per project, from /settings: the pack names are the
project's `RulePacks` setting. Nothing turns a pack on by itself - not the
model, not a guess from the files in the folder. Rules for code in a
conversation about something else are tokens spent on every request, and
the person knows what the project is for better than a guess does.

WHERE THEY GO. In the system prompt, after the project's own PRAGMA.md and
before the session block, which changes every session and so must come
last (see agent.prompts.session_block). The packs change only when the
person changes them, so a server's prompt cache keeps them from one
conversation of the project to the next. A pack turned on in the middle of
a conversation cannot be put there without the whole conversation being
read again: it goes in front of the next request instead - note().
This module asks nothing of anyone and reads only files.
"""
from __future__ import annotations

from pathlib import Path

BUILT_IN = Path(__file__).resolve().parent / "rules"
SETTING = "RulePacks"


def user_dir() -> Path:
    """Where a person's own packs are."""
    return Path.home() / ".pragma" / "rules"


def available() -> dict[str, dict]:
    """name -> {"text", "what", "tokens", "yours"}, Pragma's first, then the
    person's own; one of theirs with the same name replaces Pragma's."""
    packs: dict[str, dict] = {}
    for folder, yours in ((BUILT_IN, False), (user_dir(), True)):
        try:
            files = sorted(folder.glob("*.md"))
        except OSError:
            continue
        for path in files:
            try:
                text = path.read_text(encoding="utf-8-sig").strip()
            except OSError:
                continue
            if not text:
                continue
            first = text.splitlines()[0].lstrip("#").strip()
            what = first.split(":", 1)[1].strip() if ":" in first else first
            packs[path.stem.lower()] = {
                "text": text, "what": what, "yours": yours,
                # A rough count, for the page to say what a pack costs.
                "tokens": max(1, len(text) // 4)}
    return packs


def chosen(settings: dict) -> list[str]:
    """The pack names a project's settings hold, as written there."""
    got = (settings or {}).get(SETTING) or []
    if isinstance(got, str):
        got = got.split(",")
    return [str(n).strip().lower() for n in got if str(n).strip()]


def active(settings: dict) -> list[str]:
    """The packs a project has on that exist, in the order they are listed."""
    packs = available()
    want = set(chosen(settings))
    return [name for name in packs if name in want]


def missing(settings: dict) -> list[str]:
    """Packs a project has on whose file is gone."""
    packs = available()
    return [name for name in chosen(settings) if name not in packs]


def _texts(names: list[str]) -> str:
    packs = available()
    return "\n\n".join(packs[n]["text"] for n in names if n in packs)


def block(names: list[str]) -> str:
    """The system prompt's part for these packs, or "" for none."""
    texts = _texts(names)
    if not texts:
        return ""
    return ("\n\n## Rule packs\n\nThe person turned these on for this project's "
            "work. Follow them as you follow the project's own rules; where the "
            "two disagree, the project's own rules win.\n\n" + texts + "\n")


def note(names: list[str]) -> str:
    """The same packs, turned on in the middle of a conversation: put in front
    of the next request, and so kept in the conversation from then on."""
    texts = _texts(names)
    if not texts:
        return ""
    return ("[RULE PACKS TURNED ON]\nThe person has just turned these on for "
            "this project's work. Follow them from now on, as you follow the "
            "project's own rules; where the two disagree, the project's own "
            "rules win.\n\n" + texts + "\n[/RULE PACKS TURNED ON]")
