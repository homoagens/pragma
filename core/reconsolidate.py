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
thematically close to it. Your job: decide whether the new episode changes the
MEANING of any past episode, and if so, rewrite that episode's interpretation.

This models how human memory works: recalling an old episode in the light of a
later one can reveal it differently — an apparent failure was the first sign of
a turning point; an apparent success hid a crack. The past is re-understood.

Respond with ONLY a JSON object:
{
  "rewrites": [
    {"id": "ep_...",
     "interpretation": "the past episode's meaning, re-read in light of the new one, <= INT_CHARS chars",
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
- Only include an episode in "rewrites" if its meaning GENUINELY shifts. If the
  new episode merely repeats or is unrelated, omit it. An empty "rewrites" list
  is the normal, correct answer most of the time.
- Keep each interpretation concrete and about the WORK, not the note-taking.
- INT_CHARS chars is the real limit: on recall only the first INT_CHARS are
  shown. You are replacing a note to self, not writing a commentary. Say the
  shift in one sentence.""" \
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
                temperature=0.0,
                max_tokens=config.MEMORY_MAX_TOKENS,
                template_kwargs=config.memory_template_kwargs("write"),
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
                temperature=0.0,
                max_tokens=config.MEMORY_MAX_TOKENS,
                template_kwargs=config.memory_template_kwargs("write"),
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
