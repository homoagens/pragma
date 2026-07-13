# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# skills/episode_consolidate/skill.py — session → episode → (maybe) semantics
#
# Implements the consolidation flow of Pragma's memory architecture:
#   1. A finished session transcript is distilled by a dedicated LLM call
#      into an EPISODE: a structured record (facts in `narrative`, meaning
#      in `interpretation`, deviations in `surprises`) stored as one JSON
#      file in config.EPISODES_DIR.
#   2. If thematically similar past episodes exist, a second LLM call runs
#      the ABSTRACTION step: it may propose semantic assertions — but only
#      when supported by at least SEMANTIC_MIN_SOURCES distinct episodes —
#      and may confirm or contradict existing assertions. Confidence
#      bookkeeping is deterministic and lives here, not in the LLM.
#
# The `narrative` field is written once and never rewritten (facts are
# immutable); `interpretation` is the mutable "meaning" field, reserved
# for future reconsolidation passes.

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config
import episodes as estore
import llm_client
from json_parser import extract_json


_EPISODE_SYSTEM = """You are the memory-consolidation module of an AI coding agent.
You receive the transcript of a completed working session and write the
EPISODE: a compact, structured record of that session for the agent's
future selves.

Respond with ONLY a JSON object of this exact shape:
{
  "goal":           "what the user wanted, <= 15 words",
  "narrative":      "what was done, in order, 5-10 short lines, FACTS only",
  "surprises":      [ "anything that departed from expectation", ... ],
  "outcome":        "success" | "partial" | "failure",
  "interpretation": "1-3 sentences: what this session MEANS (fragilities, confirmations, open questions)",
  "keywords":       [ "5-10 lowercase topical keywords for retrieval" ]
}

Rules:
- Facts go in narrative, meaning goes in interpretation. Never mix them.
- surprises is the MOST IMPORTANT field: confirmed routines are forgettable,
  deviations from expectation are information. Errors, retries, unexpected
  tool behavior, wrong assumptions — record them. Empty array only if the
  session was truly uneventful.
- Keep each surprise under 200 characters.
- Mention concrete file paths and project names when they matter.
- Write keywords in the dominant language of the session."""


_SEMANTIC_SYSTEM = """You are the abstraction module of an AI coding agent's memory.
You receive a NEW episode, a set of SIMILAR past episodes, and the EXISTING
semantic assertions related to them. Your job is to distill durable, general
knowledge — and only when the evidence supports it.

Respond with ONLY a JSON object:
{
  "new_assertions": [ {"kind": "lessons" | "patterns" | "user_prefs" | "mistakes",
                       "text": "general statement, <= 200 chars",
                       "sources": ["ep_...", "ep_..."]}, ... ],
  "confirms":       [ "exact text of an existing assertion this episode strengthens", ... ],
  "contradicts":    [ "exact text of an existing assertion this episode contradicts", ... ]
}

Rules:
- A new assertion REQUIRES at least two distinct episodes as sources — cite
  their ids from the payload. One episode alone proves nothing: if a pattern
  appears only in the new episode, propose NOTHING for it. It will get its
  chance when it recurs.
- Never restate one-off task content as general knowledge.
- confirms/contradicts must copy the existing assertion text EXACTLY.
- Quality over quantity: 0-2 new assertions is the norm. Empty arrays are fine."""


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _episode_text(ep: dict) -> str:
    """Flat text used for thematic similarity scoring."""
    return " ".join([
        ep.get("goal", "") or "",
        " ".join(ep.get("keywords", []) or []),
        ep.get("narrative", "") or "",
        " ".join(ep.get("surprises", []) or []),
    ])


def _episode_lite(ep: dict) -> dict:
    """Compact view of an episode for the abstraction prompt."""
    return {
        "id":             ep.get("id", ""),
        "goal":           ep.get("goal", ""),
        "outcome":        ep.get("outcome", ""),
        "surprises":      ep.get("surprises", []),
        "interpretation": ep.get("interpretation", ""),
        "keywords":       ep.get("keywords", []),
    }


def _load_episodes(store: Path) -> list[dict]:
    out = []
    if not store.is_dir():
        return out
    for p in sorted(store.glob("ep_*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _as_text(v) -> str:
    """Normalize a field the model may return as a list into plain text.
    Guards against `narrative: ["step 1", "step 2"]` being str()-ified
    into a python-repr string."""
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    return str(v or "")


def _is_placeholder(s: str) -> bool:
    """True for empty values and for the literal ellipsis placeholders some
    models echo back from the JSON shape in the system prompt."""
    return not s or s.strip() in ("...", "…")


def _clean_list(items) -> list[str]:
    """Str-ify list items, drop empties and echoed '...' placeholders."""
    out = []
    for it in items or []:
        s = str(it).strip()
        if s and not _is_placeholder(s):
            out.append(s)
    return out


def _ask_episode(transcript: str, corrective: bool = False,
                 json_only: bool = False) -> dict:
    """One LLM call for the consolidation step. Raises on failure."""
    user_msg = f"Session transcript:\n\n{transcript}"
    if corrective:
        user_msg += (
            "\n\n[IMPORTANT: your previous attempt returned literal '...' "
            "placeholder values copied from the JSON shape. That is useless. "
            "Fill EVERY field with real content extracted from the "
            "transcript above.]"
        )
    if json_only:
        # Thinking-capable models sometimes burn the whole token budget
        # narrating a reasoning process and get truncated before any JSON
        # appears. Demand the JSON first, no prose.
        user_msg += (
            "\n\n[IMPORTANT: your previous reply was cut off before any JSON "
            "appeared — too much thinking out loud. Reply with ONLY the JSON "
            "object: the character '{' must be the FIRST character of your "
            "reply. No preamble, no reasoning narration.]"
        )
    raw = llm_client.call_llm(
        messages=[
            {"role": "system", "content": _EPISODE_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=config.SKILL_MAX_TOKENS,
    )
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError("consolidation returned non-object JSON")
    return data


def _load_learnings(path: Path) -> dict:
    if not path.exists():
        return {"entries": [], "created_at": _now()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("entries", [])
        return data
    except Exception:
        return {"entries": [], "created_at": _now()}


def episode_consolidate_detailed(transcript: str = "", workspace: str = "",
                                 source: str = "", store_dir: str = "") -> dict:
    """
    Structured-result variant of episode_consolidate. Returns:
      { "status": "ok" | "error",
        "summary": "<one-line human summary>",
        "episode_id": "...", "surprises": N,
        "new_assertions": [...], "confirmed": [...],
        "contradicted": [...], "retired": [...] }
    """
    empty = {"episode_id": "", "surprises": 0, "new_assertions": [],
             "confirmed": [], "contradicted": [], "retired": []}
    if not transcript or not transcript.strip():
        return {"status": "error", "summary": "ERROR: transcript is empty", **empty}

    store = Path(store_dir) if store_dir else Path(config.EPISODES_DIR)

    # ── 1. Consolidation: transcript → episode ──────────────────────────
    # First attempt; on failure (typically: the model narrated a thinking
    # process and got truncated before the JSON) retry once demanding
    # JSON-first output. If the LLM fails twice, do NOT lose the session:
    # fall through with empty data and let the deterministic fallback
    # below build a minimal factual episode instead.
    llm_note = ""
    try:
        ep_data = _ask_episode(transcript)
    except Exception:
        try:
            ep_data = _ask_episode(transcript, json_only=True)
        except Exception as e2:
            ep_data = {}
            llm_note = f" [consolidation LLM failed twice: {str(e2)[:120]}]"

    # Some models echo the '...' placeholders from the JSON shape instead
    # of filling the fields. Retry once with a corrective note; if it
    # happens again, fall back to a minimal deterministic episode built
    # from the transcript — a plain factual record beats a ghost of '...'.
    goal      = _as_text(ep_data.get("goal")).strip()
    narrative = _as_text(ep_data.get("narrative")).strip()
    degraded  = False
    # Placeholder retry only makes sense if the LLM is answering at all —
    # after a double failure above, go straight to the fallback.
    if (_is_placeholder(goal) or _is_placeholder(narrative)) and not llm_note:
        try:
            ep_data   = _ask_episode(transcript, corrective=True)
            goal      = _as_text(ep_data.get("goal")).strip()
            narrative = _as_text(ep_data.get("narrative")).strip()
        except Exception:
            pass
    if _is_placeholder(goal) or _is_placeholder(narrative):
        degraded  = True
        first_user = next((ln[len("USER:"):].strip()
                           for ln in transcript.splitlines()
                           if ln.startswith("USER:")), "")
        goal      = (first_user or "unlabeled session")[:200]
        narrative = transcript[:800]
        ep_data   = {}  # drop every other placeholder field

    interpretation = _as_text(ep_data.get("interpretation")).strip()
    if _is_placeholder(interpretation):
        interpretation = ""

    outcome = ep_data.get("outcome", "partial")
    if outcome not in ("success", "partial", "failure"):
        outcome = "partial"
    surprises = [s[:300] for s in _clean_list(ep_data.get("surprises"))]
    keywords  = [k.lower() for k in _clean_list(ep_data.get("keywords"))][:12]

    ep = {
        "id":  f"ep_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}",
        "ts":  _now(),
        "workspace": workspace or "",
        "source":    source or "",
        "goal":      goal[:200],
        "narrative": narrative,          # facts — immutable
        "surprises": surprises,
        "outcome":   outcome,
        "interpretation": interpretation,  # meaning — mutable
        "keywords":  keywords,
        # Surprises ARE salience: a session that deviated from expectation
        # deserves to resist forgetting longer than a routine one.
        "salience":  min(0.9, 0.4 + 0.15 * len(surprises)),
        "last_recalled": None,
        "links": [],
    }
    try:
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{ep['id']}.json").write_text(
            json.dumps(ep, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        return {"status": "error",
                "summary": f"ERROR writing episode: {e}", **empty}

    # ── Forgetting maintenance — the session's "sleep" moment ──
    # Runs right after the new episode is filed and BEFORE the abstraction
    # pass, so faded episodes neither surface as similarity candidates nor
    # become assertion sources. The fresh episode is untouchable by
    # construction (age 0 → effective salience = raw salience > threshold).
    swept = estore.sweep(store)
    _sweep_note = ""
    if swept["dormant"] or swept["deleted"]:
        _sweep_note = f"; sweep: {len(swept['dormant'])} episode(s) to dormant"
        if swept["deleted"]:
            _sweep_note += f", {len(swept['deleted'])} deleted"

    result = {"status": "ok", "summary": "", "episode_id": ep["id"],
              "surprises": len(surprises), "sweep": swept,
              "semantic_ran": False,
              "new_assertions": [], "confirmed": [], "contradicted": [],
              "retired": []}
    if degraded and llm_note:
        _degraded_note = llm_note + " — deterministic fallback episode saved"
    elif degraded:
        _degraded_note = (" [degraded: model echoed placeholders twice, "
                          "deterministic fallback used]")
    else:
        _degraded_note = ""

    # ── 2. Abstraction: episodes that recur → semantic assertions ───────
    # Runs only when at least one thematically similar past episode exists:
    # a single episode never generates knowledge on its own.
    past = [e for e in _load_episodes(store) if e.get("id") != ep["id"]]
    qtok = _tokens(_episode_text(ep))
    scored = sorted(((e, len(_tokens(_episode_text(e)) & qtok)) for e in past),
                    key=lambda t: t[1], reverse=True)
    similar = [e for e, s in scored if s >= 2][:3]  # ≥2 shared tokens = related
    if not similar:
        result["summary"] = (
            f"OK: episode {ep['id']} saved ({len(surprises)} surprises); "
            f"semantic pass skipped (no similar episodes yet)"
            + _sweep_note + _degraded_note)
        return result

    learnings_path = Path(config.LEARNINGS_PATH)
    learnings = _load_learnings(learnings_path)
    entries = learnings["entries"]

    # Related existing assertions, for confirmation/contradiction checks.
    active = [e for e in entries if e.get("status", "active") != "retired"]
    rel_scored = sorted(((e, len(_tokens(e.get("text", "")) & qtok)) for e in active),
                        key=lambda t: t[1], reverse=True)
    related = [e for e, s in rel_scored if s > 0][:8]

    payload = json.dumps({
        "new_episode":         _episode_lite(ep),
        "similar_episodes":    [_episode_lite(e) for e in similar],
        "existing_assertions": [e.get("text", "") for e in related],
    }, ensure_ascii=False, indent=2)

    result["semantic_ran"] = True   # the abstraction LLM call is about to run
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _SEMANTIC_SYSTEM},
                {"role": "user",   "content": payload},
            ],
            temperature=0.0,
            max_tokens=config.SKILL_MAX_TOKENS,
        )
        sem = extract_json(raw)
    except Exception as e:
        result["summary"] = (
            f"OK: episode {ep['id']} saved ({len(surprises)} surprises); "
            f"semantic pass failed — {e}" + _sweep_note + _degraded_note)
        return result
    if not isinstance(sem, dict):
        sem = {}

    known_ids = {ep["id"]} | {e.get("id", "") for e in similar}
    ts = _now()

    # New assertions — enforced deterministically, whatever the model says:
    # distinct sources, all from the episodes it was shown, at least
    # SEMANTIC_MIN_SOURCES of them, and no duplicate text.
    min_sources = getattr(config, "SEMANTIC_MIN_SOURCES", 2)
    for a in sem.get("new_assertions") or []:
        if not isinstance(a, dict):
            continue
        kind = a.get("kind", "")
        text = str(a.get("text", "")).strip()[:300]
        sources = sorted({str(s) for s in (a.get("sources") or []) if str(s) in known_ids})
        if kind not in ("lessons", "patterns", "user_prefs", "mistakes"):
            continue
        if not text or len(sources) < min_sources:
            continue
        if any(e.get("text") == text for e in entries):
            continue
        entry = {"kind": kind, "text": text, "label": workspace or "", "ts": ts,
                 "sources": sources, "confidence": 0.6,
                 "confirmations": 0, "contradictions": 0, "status": "active"}
        entries.append(entry)
        result["new_assertions"].append(entry)

    # Confirmations strengthen; contradictions weaken — but never one alone
    # retires consolidated knowledge (see config.SEMANTIC_RETIRE_CONTRADICTIONS).
    bonus  = getattr(config, "SEMANTIC_CONFIRM_BONUS", 0.1)
    malus  = getattr(config, "SEMANTIC_CONTRADICT_MALUS", 0.2)
    retire = getattr(config, "SEMANTIC_RETIRE_CONTRADICTIONS", 2)

    for text in sem.get("confirms") or []:
        for e in entries:
            if e.get("text") == text and e.get("status", "active") != "retired":
                e["confidence"] = min(0.95, e.get("confidence", 0.5) + bonus)
                e["confirmations"] = e.get("confirmations", 0) + 1
                e.setdefault("sources", []).append(ep["id"])
                result["confirmed"].append(text)
                break

    for text in sem.get("contradicts") or []:
        for e in entries:
            if e.get("text") == text and e.get("status", "active") != "retired":
                e["confidence"] = max(0.05, e.get("confidence", 0.5) - malus)
                e["contradictions"] = e.get("contradictions", 0) + 1
                result["contradicted"].append(text)
                if e["contradictions"] >= retire:
                    e["status"] = "retired"
                    result["retired"].append(text)
                break

    try:
        learnings_path.parent.mkdir(parents=True, exist_ok=True)
        learnings_path.write_text(
            json.dumps(learnings, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        result["summary"] = (
            f"OK: episode {ep['id']} saved; ERROR writing learnings — {e}")
        return result

    result["summary"] = (
        f"OK: episode {ep['id']} saved ({len(surprises)} surprises); "
        f"semantics: +{len(result['new_assertions'])} assertions, "
        f"{len(result['confirmed'])} confirmed, "
        f"{len(result['contradicted'])} contradicted"
        + (f", {len(result['retired'])} retired" if result["retired"] else "")
        + _sweep_note + _degraded_note)
    return result


def episode_consolidate(transcript: str = "", workspace: str = "",
                        source: str = "", store_dir: str = "") -> str:
    """
    [H] Consolidate a finished session transcript into an episodic memory
    record, then distill semantic assertions when patterns recur across
    episodes.

    transcript : the session narrative (user request + thoughts + actions +
                 observations + final). If empty, returns ERROR.
    workspace  : the cwd the session worked in (used for recall boosting
                 and as the assertion label).
    source     : free tag for provenance (e.g. "batch", "ui").
    store_dir  : episode store override. Default config.EPISODES_DIR.

    Returns "OK: episode ep_... saved (N surprises); ..." or "ERROR: ...".
    Normally invoked by the runtime at end of task, not by the agent.
    """
    return episode_consolidate_detailed(transcript, workspace, source,
                                        store_dir)["summary"]
