# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# reconsolidate.py — Stage 3 of the memory architecture: reconsolidation.
#
# The principle, from chapter 4: recall is not read-only. Memories are
# RECONSTRUCTED each time they are retrieved, in the light of what has been
# learned in the meantime. "The facts do not change — what happened happened.
# What changes is the meaning of the facts." Reconsolidation applies that
# principle at both layers of memory:
#
#   A. EPISODIC — when a new session is consolidated, the thematically closest
#      past episodes are re-read and their `interpretation` may be rewritten in
#      the light of the novelty. `narrative` (the facts) is FROZEN.
#   B. SEMANTIC — a belief that has accumulated enough independent
#      contradictions is REFORMULATED (its text rewritten to fit the evidence)
#      rather than merely retired.
#
# Two-level safety law (so reconsolidation is reinterpretation, not
# confabulation — and does not become the mechanism that implants false
# memories):
#   1. FACTS ENTAILMENT — a rewritten interpretation must stay supported by the
#      target episode's own frozen `narrative`; a reformulated belief must stay
#      supported by its cited `sources`. No new facts may be introduced.
#   2. TRUST HIERARCHY (chapter 8) — reconsolidation writes ONLY to the evolving
#      side of memory (episodes, beliefs), NEVER the constitutive core; and it
#      never fires on the strength of a single, low-provenance episode (the
#      semantic layer requires several independent contradictions; the episodic
#      layer is anchored in the target's own facts).
#
# Every rewrite is versioned (prior text kept in history), which is what makes
# reconsolidation a *coherent, traceable* evolution of memory rather than
# silent drift.

from __future__ import annotations

import config
import llm_client
from json_parser import extract_json


# ── A. Episodic reconsolidation ──────────────────────────────────────────────

_EPISODIC_SYSTEM = """You are the reconsolidation module of an AI agent's memory.
A NEW episode has just been recorded. You are given a few PAST episodes that are
thematically close to it. Your job: decide whether the new episode changes what
any past episode MEANS, and if so, revise that episode's interpretation.

This models how human memory works: an old episode recalled in the light of a
later one can turn out to mean something else - what looked settled was not,
what looked like a detail was the cause. The past is re-understood. It is still
the same past: the revised interpretation is about the OLD episode.

Respond with ONLY a JSON object:
{
  "rewrites": [
    {"id": "ep_...",
     "interpretation": "what the past episode means, as it now stands, <= INT_CHARS chars",
     "reason": "what the new episode reveals about the old one, <= 20 words"},
    ...
  ]
}

IRON RULES — this is reinterpretation, not invention:
- The FACTS DO NOT CHANGE. You may only rewrite `interpretation` (the meaning).
  You never see or touch `narrative` for editing — it is frozen truth.
- A new interpretation must remain SUPPORTED BY THAT EPISODE'S OWN narrative.
  You re-read the same facts in a new light; you must NOT import facts from the
  new episode into the old one, nor invent anything.
- REVISE, DO NOT REPLACE. The interpretation is the one lasting note on what
  that episode means. Keep what it already says that still holds - a lesson,
  something about the user, an open question - and change only what the new
  episode shows to be wrong or incomplete. A revision that drops the old
  meaning in order to comment on the new episode has lost a memory.
- IT STAYS ABOUT ITS OWN EPISODE. What the interpretation talks about is what
  happened in THAT episode. Hindsight may change how much one of its facts
  weighs ("the first sign of ...", "not the one-off it seemed"); it does not
  retell the new episode or how the story went on.
- Only include an episode in "rewrites" if its meaning GENUINELY shifts. That
  the two belong to the same story, or that the new one continues, repeats or
  confirms the old one, is a connection and not a shift: omit it. An empty
  "rewrites" list is the normal, correct answer most of the time.
- Keep each interpretation concrete and about the WORK, not the note-taking,
  in plain statements of your own: no stock turn of phrase.
- INT_CHARS chars is the real limit: on recall only the first INT_CHARS are
  shown. If the old meaning and the hindsight do not both fit, the old meaning
  that still holds comes first.""" \
    .replace("INT_CHARS", str(config.MEMORY_INTERPRETATION_CHARS))


# Enforced on the native protocol. An unparsable reply here is silently
# equivalent to "nothing was reinterpreted" (the caller returns []), so a
# malformed reply does not fail loudly — it quietly removes a mechanism the
# paper measures. Worth making impossible rather than merely rare.
_EPISODIC_SCHEMA = {
    "__name__": "reconsolidation",
    "type": "object",
    "properties": {
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id":             {"type": "string"},
                    "interpretation": {"type": "string"},
                    "reason":         {"type": "string"},
                },
                "required": ["id", "interpretation", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["rewrites"],
    "additionalProperties": False,
}


def _ep_for_prompt(ep: dict) -> dict:
    return {
        "id":             ep.get("id", ""),
        "narrative":      ep.get("narrative", ""),      # facts (context only)
        "interpretation": ep.get("interpretation", ""),  # meaning (editable)
    }


# Why the last call did nothing, or "" when it worked.
#
# Both functions below return "nothing to do" and "the call failed" as the same
# value - an empty list, None - because neither must ever break consolidation.
# That policy is right and it hid a real failure: an endpoint that blinked
# during reconsolidation produced exactly the output of a faculty that ran and
# decided no episode needed rereading. In a campaign about reinterpretation,
# that is the one confusion you cannot afford.
#
# So the reason is left here for the caller to report. Module state rather than
# a changed return type, following llm_client.LAST_STATS: the signature is used
# by a skill whose lineage feeds the frozen corpus, and widening it would ripple
# further than the problem.
LAST_ERROR: str = ""


def reconsolidate_episodes(new_ep: dict, targets: list[dict],
                           model=None) -> list[dict]:
    """Ask the model to re-read `targets` in the light of `new_ep`.

    Returns a list of {"id", "interpretation", "reason"} for the episodes whose
    meaning changed. Deterministically filtered: id must be a known target, the
    new interpretation must be non-empty and actually different from the old.
    Never raises — reconsolidation must not break consolidation.
    """
    global LAST_ERROR
    LAST_ERROR = ""
    if not targets:
        return []
    import json
    by_id = {t.get("id", ""): t for t in targets}
    payload = json.dumps({
        "new_episode": {
            "goal":           new_ep.get("goal", ""),
            "narrative":      new_ep.get("narrative", ""),
            "interpretation": new_ep.get("interpretation", ""),
            "keywords":       new_ep.get("keywords", []),
        },
        "past_episodes": [_ep_for_prompt(t) for t in targets],
    }, ensure_ascii=False, indent=2)

    try:
        with llm_client.faculty("RECONSOLIDATOR"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _EPISODIC_SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                **config.memory_call("write"),
                response_schema=_EPISODIC_SCHEMA,
            )
        data = extract_json(raw)
    except Exception as e:
        LAST_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
        return []
    if not isinstance(data, dict):
        LAST_ERROR = "reply was not JSON: " + " ".join(str(raw).split())[:120]
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for r in data.get("rewrites") or []:
        if not isinstance(r, dict):
            continue
        eid = str(r.get("id", ""))
        new_interp = str(r.get("interpretation", "")).strip()
        if eid not in by_id or eid in seen:
            continue
        if not new_interp or new_interp in ("...", "…"):
            continue
        # A rewrite that equals the current meaning is a no-op; skip it.
        if new_interp == (by_id[eid].get("interpretation", "") or "").strip():
            continue
        seen.add(eid)
        out.append({"id": eid,
                    "interpretation": new_interp[:600],
                    "reason": str(r.get("reason", "")).strip()[:200]})
    return out


# ── B. Semantic reformulation ────────────────────────────────────────────────

_SEMANTIC_SYSTEM = """You are the reconsolidation module of an AI agent's memory,
working on SEMANTIC beliefs. A belief the agent held has been contradicted by
enough independent evidence that it can no longer stand as written. A careful
professional, at this point, does not keep believing two opposite things and
does not simply erase the belief — they REFORMULATE it so it fits what they now
know.

You are given the current belief and the evidence that contradicted it. Produce
a reformulation that reconciles them — usually by adding the condition under
which the old belief held ("X is safe" → "X is safe only when Y").

Respond with ONLY a JSON object:
{
  "reformulate": true | false,
  "text": "the reformulated belief, a general statement, <= 200 chars",
  "reason": "what changed and why, <= 20 words"
}

RULES:
- Set reformulate=false when the belief is simply FALSE now and no honest
  qualified version survives — then the caller retires it. Do not manufacture a
  hollow reformulation just to keep it alive.
- The reformulation must be SUPPORTED by the evidence shown; do not invent new
  facts or conditions the evidence does not warrant.
- Keep the same subject as the original belief; you are revising a belief, not
  writing an unrelated new one."""


# Enforced on the native protocol. `reformulate` is the decisive field: a
# reply that fails to parse is read as "no defensible reformulation", which
# RETIRES the belief. A parse failure must not be able to masquerade as a
# deliberate judgment to discard one.
_REFORMULATION_SCHEMA = {
    "__name__": "reformulation",
    "type": "object",
    "properties": {
        "reformulate": {"type": "boolean"},
        "text":        {"type": "string"},
        "reason":      {"type": "string"},
    },
    "required": ["reformulate", "text", "reason"],
    "additionalProperties": False,
}


def reformulate_belief(text: str, contradicting_evidence: list[str],
                       sources_summary: list[str], model=None) -> dict | None:
    """Ask the model to reformulate a contradicted belief so it fits the
    evidence. Returns {"text", "reason"} on success, or None to signal "no
    defensible reformulation — retire it" (or on any failure: fail safe by
    retiring, the pre-Stage-3 behaviour). Never raises.
    """
    global LAST_ERROR
    LAST_ERROR = ""
    import json
    payload = json.dumps({
        "belief":                 text,
        "contradicting_evidence": [str(e)[:300] for e in (contradicting_evidence or [])],
        "supporting_sources":     [str(s)[:200] for s in (sources_summary or [])],
    }, ensure_ascii=False, indent=2)
    try:
        with llm_client.faculty("RECONSOLIDATOR"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _SEMANTIC_SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                **config.memory_call("write"),
                response_schema=_REFORMULATION_SCHEMA,
            )
        data = extract_json(raw)
    except Exception as e:
        LAST_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
        return None
    if not isinstance(data, dict) or not data.get("reformulate"):
        return None
    new_text = str(data.get("text", "")).strip()[:300]
    if not new_text or new_text in ("...", "…") or new_text == text.strip():
        return None
    return {"text": new_text, "reason": str(data.get("reason", "")).strip()[:200]}


# ── C. A belief whose sources were re-read ───────────────────────────────────
#
# NOT THE SAME QUESTION AS B. There, a belief has been contradicted and the
# only way to keep it is to rewrite it. Here nobody has contradicted anything:
# the episodes a belief rests on have been re-read, and the question is whether
# the belief still says what they support. Asked with B's prompt - which opens
# by telling the model the belief "can no longer stand as written", and whose
# only way of leaving it alone is to declare it false - a belief came back
# reworded whether or not anything under it had changed. The usual answer here
# is that it still stands, and the prompt has to make that answer available.
#
# AND IT IS ASKED AGAINST WHAT HAPPENED, not only against what the sources are
# now taken to mean. An interpretation is rewritten for a reason of its own,
# and the new one may no longer mention what a belief drew from that episode.
# Shown the meanings alone, the model takes that silence for a contradiction
# and writes a different belief in the old one's place. The narrative is the
# part of an episode that does not change: it is the ground the belief was
# drawn from, and it is still there.

_REVIEW_SYSTEM = """You are the reconsolidation module of an AI agent's memory,
working on SEMANTIC beliefs. A belief rests on episodes. What some of those
episodes are taken to MEAN has since been revised; what HAPPENED in them has
not changed and cannot. Nobody has contradicted the belief. Your job: check
whether it still says what its sources support.

You are given the belief and its sources: for each, what it was about, what
happened in it, what it is taken to mean now, and whether that meaning was
revised.

Respond with ONLY a JSON object:
{
  "reformulate": true | false,
  "text": "the belief as it should now read, a general statement, <= 200 chars",
  "reason": "what in the sources the old wording no longer fits, <= 20 words"
}

RULES:
- Most of the time the belief STILL STANDS, and a belief is meant to be
  steadier than the episodes under it. Then set reformulate=false and leave
  "text" and "reason" empty. This is the normal, correct answer.
- WHAT HAPPENED IS THE GROUND. A belief stands for as long as what happened in
  its sources supports it. A revised meaning that no longer mentions what the
  belief says has not taken that support away: the episode was re-read for
  something else.
- Set reformulate=true only when the revised meanings, read together with what
  happened, show the belief to be too broad, too narrow, or pointed the wrong
  way. Then change only that: keep its subject, and as much of its wording as
  still holds. A sentence about something else is a different belief, not a
  rewording of this one.
- The new wording must be SUPPORTED by what is shown; do not invent facts or
  conditions the sources do not warrant.
- A belief is a general statement. Do not turn it into a summary of its
  sources, and do not reword it for style."""

# How many sources a belief is shown with: the revised ones come first.
_REVIEW_SOURCES = 6


def review_belief(text: str, sources: list[dict], model=None) -> dict | None:
    """Ask whether a belief still says what its sources support, now that some
    of them have been re-read.

    `sources` are the episodes it rests on, each {"about", "happened",
    "means_now", "revised"}. Returns {"text", "reason"} when it should be
    reworded, or None to leave it as it is - which is also what any failure
    returns: a belief is never retired from here. Never raises.
    """
    global LAST_ERROR
    LAST_ERROR = ""
    import json
    payload = json.dumps({
        "belief":  text,
        "sources": [{"about":           str(s.get("about", "") or "")[:200],
                     "happened":        str(s.get("happened", "") or "")[:400],
                     "means_now":       str(s.get("means_now", "") or "")[:300],
                     "meaning_revised": bool(s.get("revised"))}
                    for s in (sources or [])[:_REVIEW_SOURCES]],
    }, ensure_ascii=False, indent=2)
    try:
        with llm_client.faculty("RECONSOLIDATOR"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _REVIEW_SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                **config.memory_call("write"),
                response_schema=_REFORMULATION_SCHEMA,
            )
        data = extract_json(raw)
    except Exception as e:
        LAST_ERROR = f"{type(e).__name__}: {str(e)[:160]}"
        return None
    if not isinstance(data, dict) or not data.get("reformulate"):
        return None
    new_text = str(data.get("text", "")).strip()[:300]
    if not new_text or new_text in ("...", "…") or new_text == text.strip():
        return None
    return {"text": new_text, "reason": str(data.get("reason", "")).strip()[:200]}
