# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# segmenter.py — which parts of a conversation deserve to become memories.
#
# A batch run has one request, so what becomes an episode is settled by fiat.
# A conversation does not: an evening contains work, corrections, and small
# talk, and storing all of it in the same way is not memory but transcription.
#
# THIS IS THE FIRST HALF OF THE FACULTY: keep or discard, over boundaries that
# are already known (the user's own messages). The second half — merging
# adjacent turns that belong to one event, and cutting inside a turn — is not
# implemented yet.
#
# WHY IT RUNS BEFORE CONSOLIDATION, NOT AFTER. Discarding by importance would
# be simpler: consolidate, then drop anything scored low. It does not work.
# Importance only exists once the episode has been written, later episodes link
# to earlier ones, and removing one afterwards leaves those links pointing at
# nothing. Observed directly: in a four-turn session the fourth episode linked
# to the third. The judgement has to come first.
#
# WHY THE PROMPT IS SMALL. Deciding whether a turn is memorable needs what the
# user asked, not the mechanics of how it was carried out. Sending only the
# user messages keeps a thirty-turn session at a couple of thousand tokens,
# which is affordable on the same model that runs everything else.
#
# It writes nothing. It returns indices.

from __future__ import annotations

import json

import config
import llm_client
from json_parser import extract_json

_SYSTEM = """You decide which turns of a conversation are worth remembering.

You receive the user's messages from one session, numbered. For each, decide
whether it should become a stored memory.

Respond with ONLY a JSON object:
{
  "keep":   [ 2, 3 ],
  "reason": "<one short line: what you kept and what you dropped>"
}

KEEP a turn when it carries something a future session would be worse off
without:
- work done, decided, or attempted, and how it went
- a fact about the user, their projects, their constraints or preferences
- a correction or a change of mind — including one that reframes an earlier
  turn, which is exactly what later reinterpretation needs
- a problem encountered, a lesson, anything surprising

DROP a turn when nothing would be lost:
- greetings, thanks, acknowledgements, small talk
- questions about the environment whose answer is already knowable
  ("which folder are you in?", "what can you do?")
- a request the agent could not act on, that led nowhere

BE STINGY. Most of a conversation is not memorable, and an empty "keep" list
is a perfectly good answer for a session that was all small talk. A store
where everything is a memory is one where nothing is salient.

Judge each turn on its own worth, not on its position: the last turn is not
automatically important, and the first is not automatically context."""

_SCHEMA = {
    "__name__": "segmentation",
    "type": "object",
    "properties": {
        "keep":   {"type": "array", "items": {"type": "integer"}},
        "reason": {"type": "string"},
    },
    "required": ["keep", "reason"],
    "additionalProperties": False,
}


def select_memorable(user_turns: list[str], model=None) -> tuple[list[int], str]:
    """Return (indices to keep, reason). Indices are 0-based.

    Never raises. On any failure everything is kept: a faculty that cannot
    decide must not be the reason a memory is lost — the cost of keeping a
    dull episode is far below the cost of dropping a real one.
    """
    if not user_turns:
        return [], ""
    if len(user_turns) == 1:
        # Nothing to weigh one turn against, and a session someone bothered to
        # start is worth more than the doubt.
        return [0], "single turn kept"

    numbered = "\n".join(f"{i + 1}. {t.strip()[:500]}"
                         for i, t in enumerate(user_turns))
    try:
        raw = llm_client.call_llm(
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": numbered}],
            model=model,
            temperature=0.0,
            max_tokens=config.SKILL_MAX_TOKENS,
            response_schema=_SCHEMA,
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("non-object reply")
        keep = data.get("keep")
        if not isinstance(keep, list):
            raise ValueError("no keep list")
        # 1-based in the prompt because models count from one; anything out of
        # range is a hallucinated index and is dropped rather than trusted.
        idx = sorted({int(n) - 1 for n in keep
                      if isinstance(n, (int, float))
                      and 0 < int(n) <= len(user_turns)})
        return idx, str(data.get("reason", ""))[:200]
    except Exception as e:
        if getattr(config, "DEBUG", False):
            print(f"[segmenter] failed ({e}); keeping every turn")
        return list(range(len(user_turns))), "segmenter unavailable — kept all"


def as_json(indices: list[int], total: int) -> str:
    """Compact record of the decision, for the session log."""
    return json.dumps({"kept": [i + 1 for i in indices], "of": total})
