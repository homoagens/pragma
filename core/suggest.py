#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""What you might ask next: three questions, offered under the empty prompt.

A FACULTY, not a second model. The obvious way to do this is a small model
kept running beside the big one, and it costs a second server, a slice of
VRAM, a fourth role in the catalogue and one more thing that has to be alive
for a prompt to be drawn. The other obvious way is to ask the agent for the
suggestions along with its answer, which is worse in a quieter way: it makes
the model writing the reply also think about what you will ask next, and on a
reasoning model that lands inside the reasoning of the reply. The thing you
care about pays for the thing you do not.

So it is one short call of its own, after the answer is on the screen, on the
`recall` role - the one already meant to be fast, and the one /configure lets
you tell not to reason. It never blocks the prompt: the line comes back
immediately and the questions arrive into it, or do not.

OFF unless asked for. It is an extra call per turn on a local model that is
shared with everything else, and a machine with one slot pays for it in the
queue. SUGGEST_NEXT=on turns it on, per project, from /settings.
"""
from __future__ import annotations

import os

import config
import llm_client
from json_parser import extract_json

_SYSTEM = """You read the last exchange of a conversation and guess what the
person is most likely to ask next.

Rules:
- Write QUESTIONS OR REQUESTS the person would plausibly type, not topics.
- Write them in the language the person is using, whatever it is.
- Keep each one short: one line, no more than about twelve words.
- Make them different from one another. Three near-identical questions are
  worth one suggestion, and the person has to read all three to find that out.
- Follow the thread that is actually open. The best suggestion is usually the
  obvious next step of what was just done, not a new subject.
- Suggest nothing you were not given grounds for. If the exchange does not
  point anywhere in particular, return fewer, or none at all.

Answer as JSON: {"questions": ["...", "...", "..."]}"""

_SCHEMA = {
    "__name__": "suggestions",
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions"],
    "additionalProperties": False,
}

# What the model is shown of the turn. Enough for the thread to be legible,
# short enough that the call stays cheap: this runs on every turn.
ASKED_CHARS = 700
ANSWERED_CHARS = 1400
MAX_QUESTIONS = 3
MAX_CHARS = 90

# A SUGGESTION HAS A SHELF LIFE. The harness's own timeout is generous because
# a consolidation is worth waiting for; this is not. A guess that arrives after
# the line has been typed is worth nothing, and against a server that accepts
# the connection and then says nothing the default would leave one thread
# blocked per turn, stacking up for as long as the endpoint stayed sick.
TIMEOUT = int(os.environ.get("SUGGEST_TIMEOUT", "") or 20)


def enabled() -> bool:
    """Off unless /configure said otherwise, for the whole harness."""
    try:
        return bool(config.suggest_next())
    except Exception:
        return False


def next_questions(asked: str, answered: str, model=None) -> list[str]:
    """Three things the person might type next, or [] - never raises.

    A suggestion that fails is a suggestion that is not offered. Nothing here
    is worth interrupting a conversation for, and the caller runs it off the
    critical path precisely so that a slow or dead endpoint costs nothing.
    """
    asked, answered = (asked or "").strip(), (answered or "").strip()
    if not asked or not answered:
        return []
    payload = (f"THEY ASKED:\n{asked[:ASKED_CHARS]}\n\n"
               f"PRAGMA ANSWERED:\n{answered[:ANSWERED_CHARS]}")
    try:
        with llm_client.faculty("SUGGESTER"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                timeout=TIMEOUT,
                **config.memory_call("select"),
                response_schema=_SCHEMA,
            )
        data = extract_json(raw) or {}
    except Exception:
        return []
    out = []
    for q in (data.get("questions") or [])[:MAX_QUESTIONS]:
        q = " ".join(str(q).split())
        # A model that answers the question instead of asking it produces a
        # paragraph. One line is the contract; anything longer is not a
        # suggestion and would break the prompt's layout anyway.
        if q and len(q) <= MAX_CHARS and q not in out:
            out.append(q)
    return out
