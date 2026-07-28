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

_SYSTEM = """You decide where one experience ends and the next begins, and
which of them are worth remembering.

You receive the user's messages from one session, numbered in order. Divide
them into consecutive segments, then decide for each segment whether it should
become a stored memory.

Respond with ONLY a JSON object:
{
  "segments": [
    {"turns": [1, 2], "keep": false, "why": "opening small talk"},
    {"turns": [3, 4], "keep": true,  "why": "the topic and its correction"}
  ],
  "reason": "<one short line about the session as a whole>"
}

Every turn must appear in exactly one segment, and segments must be
consecutive: [1,2] then [3,4], never [1,3].

WHEN TO PUT TURNS TOGETHER. One segment is one experience. Turns belong
together when they are the same piece of work carried forward — a request and
its refinement, a question and the correction that reframes it, an attempt and
its outcome. Kept together, the memory holds what happened AND how it turned
out.

WHEN TO SEPARATE. A new subject, a new task, a return to something unrelated.
Be careful here: merging too much is as damaging as merging too little. A
session folded into one segment produces a memory whose importance is the
average of everything said in it, and an average is exactly what hides a
consequential moment among routine ones. When two turns are only adjacent in
time, separate them.

KEEP a segment when it carries something a future session would be worse off
without:
- work done, decided, or attempted, and how it went
- a fact about the user, their projects, their constraints or preferences
- a correction or a change of mind — including one that reframes an earlier
  turn, which is exactly what later reinterpretation needs
- a problem encountered, a lesson, anything surprising

DROP a segment when nothing would be lost:
- greetings, thanks, acknowledgements, small talk
- questions about the environment whose answer is already knowable
  ("which folder are you in?", "what can you do?")
- a request the agent could not act on, that led nowhere

A SEGMENT IS WORTH WHAT ITS BEST PART IS WORTH, not what its tone is. Judge it
by the most valuable thing in it, never by the register of the exchange around
that thing. "Hi! I'm Mario, what's your name?" reads as a greeting and is one,
but it also states who the user is — and a name is among the most reusable
facts there are. Keep the segment. The same applies to anything durable
mentioned in passing: a deadline, a tool they use, a constraint they work
under, a preference. Pleasantries around a fact do not make the fact
forgettable.

BE STINGY OTHERWISE. Most of a conversation is not memorable, and a session
where every segment is dropped is a perfectly good answer for an evening of
small talk. A store where everything is a memory is one where nothing is
salient.

Judge each segment on its own worth, not on its position: the last is not
automatically important, and the first is not automatically context."""

_SCHEMA = {
    "__name__": "segmentation",
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turns": {"type": "array", "items": {"type": "integer"}},
                    "keep":  {"type": "boolean"},
                    "why":   {"type": "string"},
                },
                "required": ["turns", "keep", "why"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["segments", "reason"],
    "additionalProperties": False,
}


def _validate(segments, n: int) -> list[tuple[list[int], bool, str]]:
    """Turn the model's segments into a partition, or raise.

    A grammar can force the shape of the reply; it cannot force the shape to
    be a partition. Overlapping segments would consolidate the same turn
    twice, gaps would drop turns nobody decided to drop, and an out-of-order
    list would join experiences that never touched. All three are silent, so
    each is checked rather than trusted.
    """
    if not isinstance(segments, list) or not segments:
        raise ValueError("no segments")
    out, seen = [], []
    for seg in segments:
        if not isinstance(seg, dict):
            raise ValueError("segment is not an object")
        turns = [int(t) - 1 for t in (seg.get("turns") or [])
                 if isinstance(t, (int, float))]
        if not turns:
            raise ValueError("empty segment")
        if any(t < 0 or t >= n for t in turns):
            raise ValueError("turn out of range")
        if turns != list(range(turns[0], turns[-1] + 1)):
            raise ValueError("segment is not consecutive")
        out.append((turns, bool(seg.get("keep")), str(seg.get("why", ""))[:120]))
        seen.extend(turns)
    if sorted(seen) != list(range(n)):
        raise ValueError("segments do not partition the turns")
    return out


def segment(user_turns: list[str], model=None) -> tuple[list[tuple[list[int], bool, str]], str]:
    """Divide a session into experiences and say which are worth keeping.

    Returns ([(turn indices, keep, why), ...], reason) with 0-based indices.

    Never raises. On any failure each turn becomes its own kept segment, which
    is what the session did before this faculty existed: a faculty that cannot
    decide must not be the reason a memory is lost, and the cost of keeping a
    dull episode is far below the cost of dropping a real one.
    """
    n = len(user_turns)
    if n == 0:
        return [], ""
    if n == 1:
        # Nothing to weigh one turn against, and a session someone bothered to
        # start is worth more than the doubt.
        return [([0], True, "single turn")], "single turn kept"

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
        return _validate(data.get("segments"), n), str(data.get("reason", ""))[:200]
    except Exception as e:
        if getattr(config, "DEBUG", False):
            print(f"[segmenter] failed ({e}); one kept segment per turn")
        return ([([i], True, "") for i in range(n)],
                "segmenter unavailable — kept every turn separately")


def describe(segments, total: int) -> str:
    """One line for the session log."""
    kept = [s for s in segments if s[1]]
    # Counted over ALL segments, not just the kept ones: a dropped segment
    # that merged two turns is still a grouping decision, and hiding it made
    # the line report one merge where the model had made two.
    merged = sum(1 for s in segments if len(s[0]) > 1)
    parts = [f"{len(kept)} of {len(segments)} segment(s) kept "
             f"from {total} turn(s)"]
    if merged:
        parts.append(f"{merged} merged")
    return ", ".join(parts)


def as_json(segments, total: int) -> str:
    """Compact record of the decision."""
    return json.dumps({"of": total,
                       "segments": [{"turns": [i + 1 for i in t],
                                     "keep": k, "why": w}
                                    for t, k, w in segments]})
