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
import reconsolidate
from json_parser import extract_json
try:                      # core/ is normally on sys.path directly
    import clock
except ImportError:       # imported as a package instead
    from core import clock


_EPISODE_SYSTEM = """You are the memory-consolidation module of an AI agent.
You receive the transcript of a completed working session and write the
EPISODE: a compact, structured record of that session for the agent's
future selves.

Respond with ONLY a JSON object of this exact shape:
{
  "goal":           "what the session was really about, in the user's terms, <= 15 words",
  "narrative":      "what happened and what was learned, FACTS only, <= NAR_CHARS chars",
  "surprises":      [ "anything that departed from expectation", ... ],
  "importance":     0.0-1.0,
  "outcome":        "success" | "partial" | "failure",
  "interpretation": "what this session MEANS (fragilities, confirmations, open questions), <= INT_CHARS chars",
  "keywords":       [ "5-10 lowercase topical keywords for retrieval" ]
}

Rules:
- Center the episode on the SUBSTANCE of the session — what the work was
  about and what was learned about the user's world — NOT on the mechanics
  of how you carried it out. Prefer "Recorded a production outage caused by
  a Friday deploy; lesson: never release on Friday" over "Appended an entry
  to diario.md". The file you edited is not the point; what it SAYS is.
- AN EPISODE IS WORTH WHAT ITS BEST PART IS WORTH, and `goal` must name that
  part. The most reusable thing in a session is not always the subject that
  took the most words. When the user says who they are, what they work under,
  or what they prefer — while the conversation is nominally about something
  else — THAT is the episode's substance. "Mario, 57, asks what the agent can
  remember" is a memory; "User onboarding: explores AI capabilities" buries
  the one durable fact inside a narrative about the agent itself. A future
  self looking for the user's name must find it in the goal, not only in a
  sentence halfway through the narrative.
- Facts go in narrative, meaning goes in interpretation. Never mix them.
- The length limits are real, not decoration. When this episode is recalled,
  only the first NAR_CHARS chars of narrative and the first INT_CHARS of
  interpretation are shown — past that it is cut mid-sentence and your future
  self never reads it. Do not write to fill the space: write the pill. Put the
  part that matters FIRST, drop the throat-clearing, and prefer one exact
  sentence to three approximate ones. A memory is a note to yourself, not a
  report to a supervisor.
- surprises are departures from expectation, in the WORK (an unexpected
  outcome, a conflict, a belief challenged by facts, a costly mistake) or in
  the TOOLS (something behaved unexpectedly). Empty array if nothing was
  surprising — which is common and fine.
- importance = how much this session matters for the FUTURE, on 0.0-1.0.
  This is SEPARATE from surprise. A thing can be unsurprising yet very
  important: a student's persistent weak spot flagged "to review next time",
  a decision that will shape later work, a hard-won rule, a client's stated
  preference. Score those HIGH (0.7-0.9) even with zero surprises. Score
  truly routine, one-off busywork LOW (0.1-0.3). A painful mistake or crisis
  is both surprising AND important (~0.9). When in doubt, ask: "will the
  agent's future self be worse off if this is forgotten?"
- Judge importance by what the session YIELDS, never by its register. Who the
  user is — name, age, role, the constraints they work under, their stated
  preferences — is among the most reusable knowledge a session can produce:
  score it 0.6-0.8 even when it was said in passing, even in a conversation
  where no work was done. Conversely score LOW (0.1-0.3) a subject that was
  discussed and closed with nothing carried forward: trivia, a lookup whose
  answer goes stale, chat with no fact in it. A pleasant tone does not make a
  fact forgettable, and an earnest one does not make small talk matter.
- Score what this session ADDS, not what it mentions. A fact the user states
  HERE is a yield; the same fact merely referred to again later is not — the
  episode that first recorded it already holds it, and scoring the echo as
  highly as the original makes every later session look equally important. If
  you would write the same `goal` for two sessions, one of them is wrong: the
  second one's goal is whatever was new in it, however slight.
- Mention tool mechanics (which skill, how you formatted a file) ONLY when
  they carried a real, reusable lesson. Never frame a routine "I wrote or
  edited a file" as the point of the episode.
- keywords: the SUBJECT of the work — people, decisions, problems, domains —
  not your tools or file names. In the session's dominant language. Include
  the user's own name whenever they state it: it is how a later session finds
  everything else about them.
- Keep each surprise under 200 characters.""" \
    .replace("NAR_CHARS", str(config.MEMORY_NARRATIVE_CHARS)) \
    .replace("INT_CHARS", str(config.MEMORY_INTERPRETATION_CHARS))


# The same contract as _EPISODE_SYSTEM, in a form the server can enforce.
# On the native protocol this is compiled into a grammar, so a truncated or
# malformed episode cannot be produced — the failure mode the `json_only`
# retry below exists to recover from. On the text protocol it is ignored.
# Deliberately no length bounds: the prompt asks for pills, and a grammar
# that cut a field at N characters would sever a sentence mid-word.
_EPISODE_SCHEMA = {
    "__name__": "episode",
    "type": "object",
    "properties": {
        "goal":           {"type": "string"},
        "narrative":      {"type": "string"},
        "surprises":      {"type": "array", "items": {"type": "string"}},
        "importance":     {"type": "number"},
        "outcome":        {"type": "string",
                           "enum": ["success", "partial", "failure"]},
        "interpretation": {"type": "string"},
        "keywords":       {"type": "array", "items": {"type": "string"}},
    },
    "required": ["goal", "narrative", "surprises", "importance", "outcome",
                 "interpretation", "keywords"],
    "additionalProperties": False,
}


_SEMANTIC_SYSTEM = """You are the abstraction module of an AI agent's memory.
You receive a NEW episode, a set of SIMILAR past episodes, and the EXISTING
semantic assertions related to them. Distill durable, general knowledge
ABOUT THE USER'S WORLD — and only when the evidence supports it.

Respond with ONLY a JSON object:
{
  "new_assertions": [ {"kind": "lessons" | "patterns" | "user_prefs" | "mistakes",
                       "text": "general statement, <= 200 chars",
                       "sources": ["ep_...", "ep_..."]}, ... ],
  "confirms":       [ "exact text of an existing assertion this episode strengthens", ... ],
  "contradicts":    [ "exact text of an existing assertion this episode contradicts", ... ]
}

WHAT to distill — general truths about the domain and the user's work:
- recurring situations and their outcomes ("clients with vague requirements
  on a fixed price → cost overruns");
- practices that reliably help or hurt ("deploying on Friday → weekend
  incidents");
- the user's preferences and beliefs, INCLUDING tentative ones ("the user
  believes fixed-price contracts are safer"). Capturing a belief even at low
  confidence is valuable: it can later be confirmed or CONTRADICTED, which is
  how the agent changes its mind.

WHAT NOT to distill (skip these entirely — they are noise, not knowledge):
- rules about how to use your own editing tools, or how to format files;
- rules about the ACTIVITY of keeping the record itself. "The user maintains
  a journal", "the user logs lessons in markdown", "the user documents cases
  chronologically" — these describe the note-taking, not the user's WORLD.
  They feel true because they recur every session, but they teach the agent
  NOTHING about the domain. Never distill them, however often they recur.

Rules:
- A new assertion REQUIRES at least two distinct episodes as sources — cite
  their ids from the payload. One episode alone is an anecdote: propose
  NOTHING for it; it gets its chance when it recurs.
- CONTRADICTION IS NOT OPTIONAL. When the new episode's facts run against an
  existing assertion, you MUST put that assertion's exact text in
  "contradicts". Do NOT dodge it by adding a fresh opposite rule and leaving
  the old one standing — that leaves the memory believing two opposite things.
  Example: the store holds "fixed-price contracts are safer" and the new
  episode is a fixed-price project that lost money → put "fixed-price
  contracts are safer" in contradicts (you may ALSO add the refined rule,
  but the contradiction is mandatory). Changing your mind means retiring the
  old belief, not hoarding both.
- confirms/contradicts must copy the existing assertion text EXACTLY.
- Quality over quantity: 0-2 new assertions is the norm. Empty arrays are fine."""


# The `kind` enum is the part worth enforcing: the admission code below drops
# any assertion whose kind is not one of these four, so an invalid label used
# to cost a whole belief. Under a grammar it cannot be emitted at all.
_SEMANTIC_SCHEMA = {
    "__name__": "semantic",
    "type": "object",
    "properties": {
        "new_assertions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind":    {"type": "string",
                                "enum": ["lessons", "patterns",
                                         "user_prefs", "mistakes"]},
                    "text":    {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "text", "sources"],
                "additionalProperties": False,
            },
        },
        "confirms":    {"type": "array", "items": {"type": "string"}},
        "contradicts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["new_assertions", "confirms", "contradicts"],
    "additionalProperties": False,
}


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _now() -> str:
    return clock.stamp()


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
    with llm_client.faculty("CONSOLIDATOR"):
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _EPISODE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=config.MEMORY_MAX_TOKENS,
            template_kwargs=config.memory_template_kwargs("write"),
            response_schema=_EPISODE_SCHEMA,
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

    # Importance: the consolidator's judgment of how much this matters for the
    # future, SEPARATE from surprise. Default to a moderate value when absent
    # (old episodes / degraded fallback) so salience never collapses.
    try:
        importance = float(ep_data.get("importance", 0.4))
    except Exception:
        importance = 0.4
    importance = max(0.0, min(1.0, importance))

    # Salience = unexpected (surprises) + important (importance). This is the
    # book's "salient = unexpected, important, or recurrent": before, only
    # surprises counted, so a routine session weighed more than an unsurprising
    # but crucial one (a student's persistent weak spot). Now importance lifts
    # those too. See config.SALIENCE_*.
    salience = min(
        getattr(config, "SALIENCE_CAP", 0.95),
        getattr(config, "SALIENCE_BASE", 0.30)
        + getattr(config, "SALIENCE_SURPRISE_WEIGHT", 0.12) * len(surprises)
        + getattr(config, "SALIENCE_IMPORTANCE_WEIGHT", 0.40) * importance,
    )

    ep = {
        "id":  f"ep_{clock.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}",
        "ts":  _now(),
        "workspace": workspace or "",
        "source":    source or "",
        # Provenance: the model that actually produced this session — resolved
        # from the endpoint when available, else the configured label.
        "model": getattr(config, "SERVED_MODEL", "") or config.DEFAULT_MODEL,
        "goal":      goal[:200],
        "narrative": narrative,          # facts — immutable
        "surprises": surprises,
        "importance": round(importance, 3),
        "outcome":   outcome,
        "interpretation": interpretation,  # meaning — mutable
        "keywords":  keywords,
        "salience":  round(salience, 4),
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
              "retired": [], "reconsolidated": [], "reformulated": [],
              "reconsolidate_error": ""}
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

    # ── 2b. Reconsolidation (episodic) — recall rewrites MEANING, not facts ──
    # Re-read the thematically closest past episodes in the light of the new
    # one. Their `interpretation` may change; `narrative` (facts) is frozen.
    # Rewrites are versioned in `interpretation_history`, and a bidirectional
    # thematic `link` is recorded (which also protects both episodes from
    # eventual hard-deletion — see episodes._protected_ids).
    recon_interps: dict[str, str] = {}   # id → new interpretation (for the A→B bridge)
    if getattr(config, "RECONSOLIDATION_ENABLED", True):
        try:
            targets = similar[:getattr(config, "RECONSOLIDATE_MAX_EPISODES", 3)]
            rewrites = reconsolidate.reconsolidate_episodes(ep, targets)
            linked: list[str] = []
            for rw in rewrites:
                tp = store / f"{rw['id']}.json"
                try:
                    tgt = json.loads(tp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                hist = tgt.get("interpretation_history") or []
                hist.append({"ts": _now(),
                             "text": tgt.get("interpretation", ""),
                             "trigger": ep["id"],
                             "reason": rw.get("reason", "")})
                tgt["interpretation_history"] = hist
                tgt["interpretation"] = rw["interpretation"]  # facts untouched
                tl = set(tgt.get("links") or [])
                tl.add(ep["id"])
                tgt["links"] = sorted(tl)
                estore.save(tp, tgt)
                linked.append(rw["id"])
                recon_interps[rw["id"]] = rw["interpretation"]
                result["reconsolidated"].append(
                    {"id": rw["id"], "reason": rw.get("reason", "")})
            if linked:
                ep["links"] = sorted(set(ep.get("links") or []) | set(linked))
                estore.save(store / f"{ep['id']}.json", ep)
            # Not breaking consolidation is the policy; being silent about it
            # was an accident. reconsolidate.LAST_ERROR distinguishes "nothing
            # needed rereading" from "the faculty could not run" - which the
            # empty list alone cannot.
            if getattr(reconsolidate, "LAST_ERROR", ""):
                result["reconsolidate_error"] = reconsolidate.LAST_ERROR
        except Exception as e:
            # Still never fatal, but no longer invisible.
            result["reconsolidate_error"] = f"{type(e).__name__}: {str(e)[:160]}"

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
        with llm_client.faculty("ABSTRACTOR"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _SEMANTIC_SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                temperature=0.0,
                max_tokens=config.MEMORY_MAX_TOKENS,
                template_kwargs=config.memory_template_kwargs("write"),
                response_schema=_SEMANTIC_SCHEMA,
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
    reformulate_at = getattr(config, "RECONSOLIDATE_REFORMULATE_AT", retire)
    recon_on = getattr(config, "RECONSOLIDATION_ENABLED", True)
    # id → episode, so a contradicted belief's sources can be summarized for
    # the reformulation call (the "facts" that must keep supporting it).
    ep_by_id = {e.get("id", ""): e for e in past}
    ep_by_id[ep["id"]] = ep

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
                if e["contradictions"] >= reformulate_at:
                    # Stage 3 (semantic reconsolidation): before retiring a
                    # sufficiently-contradicted belief, try to REFORMULATE it so
                    # it fits the evidence (e.g. add the condition under which it
                    # held). Retirement is the fallback when no honest qualified
                    # version survives.
                    reformed = None
                    if recon_on:
                        evidence = [ep.get("goal", "")] + list(ep.get("surprises") or [])
                        srcs = [ep_by_id[s].get("goal", "")
                                for s in e.get("sources", [])
                                if s in ep_by_id and ep_by_id[s].get("goal")]
                        reformed = reconsolidate.reformulate_belief(
                            e.get("text", ""), evidence, srcs)
                    if reformed:
                        hist = e.get("text_history") or []
                        hist.append({"ts": ts, "text": e.get("text", ""),
                                     "reason": reformed.get("reason", "")})
                        e["text_history"] = hist
                        old_text = e["text"]
                        e["text"] = reformed["text"]
                        e["contradictions"] = 0   # incorporated into the new text
                        e["reformulations"] = e.get("reformulations", 0) + 1
                        # a freshly reconciled belief rebounds off the malus floor
                        e["confidence"] = max(e.get("confidence", 0.5), 0.5)
                        if ep["id"] not in e.get("sources", []):
                            e.setdefault("sources", []).append(ep["id"])
                        result["reformulated"].append(
                            {"from": old_text, "to": e["text"],
                             "reason": reformed.get("reason", "")})
                    else:
                        e["status"] = "retired"
                        result["retired"].append(text)
                break

    # ── Bridge A→B: episodic reconsolidation drives semantic reformulation ──
    # The abstractor's explicit `contradicts` is fragile (model-dependent). But
    # if the episodes a belief RESTS ON have just been reinterpreted, that is a
    # robust signal the belief itself may be stale — even with zero
    # contradictions. Reformulate it in the light of its sources' new meanings.
    # This path never retires: it only rewrites when a better version exists.
    bridge_min = getattr(config, "RECONSOLIDATE_BRIDGE_MIN_SOURCES", 2)
    if recon_on and recon_interps and bridge_min > 0:
        handled = ({r["from"] for r in result["reformulated"]}
                   | set(result["retired"])
                   | {a["text"] for a in result["new_assertions"]})
        for e in entries:
            if e.get("status", "active") == "retired":
                continue
            text = e.get("text", "")
            if text in handled:
                continue
            shifted = [s for s in e.get("sources", []) if s in recon_interps]
            if len(shifted) < bridge_min:
                continue
            evidence = [recon_interps[s] for s in shifted]
            srcs = [ep_by_id[s].get("goal", "") for s in e.get("sources", [])
                    if s in ep_by_id and ep_by_id[s].get("goal")]
            reformed = reconsolidate.reformulate_belief(text, evidence, srcs)
            if not reformed:
                continue  # no defensible rewrite → leave the belief as-is
            hist = e.get("text_history") or []
            hist.append({"ts": ts, "text": text,
                         "reason": reformed.get("reason", ""), "via": "bridge"})
            e["text_history"] = hist
            e["text"] = reformed["text"]
            e["reformulations"] = e.get("reformulations", 0) + 1
            result["reformulated"].append(
                {"from": text, "to": e["text"],
                 "reason": reformed.get("reason", ""), "via": "bridge"})

    try:
        learnings_path.parent.mkdir(parents=True, exist_ok=True)
        learnings_path.write_text(
            json.dumps(learnings, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        result["summary"] = (
            f"OK: episode {ep['id']} saved; ERROR writing learnings — {e}")
        return result

    _recon_note = ""
    if result["reconsolidated"]:
        _recon_note += f"; reconsolidated {len(result['reconsolidated'])} episode(s)"
    if result["reformulated"]:
        _recon_note += f", reformulated {len(result['reformulated'])} belief(s)"
    if result.get("reconsolidate_error"):
        _recon_note += f"; RECONSOLIDATOR FAILED - {result['reconsolidate_error']}"
    result["summary"] = (
        f"OK: episode {ep['id']} saved ({len(surprises)} surprises); "
        f"semantics: +{len(result['new_assertions'])} assertions, "
        f"{len(result['confirmed'])} confirmed, "
        f"{len(result['contradicted'])} contradicted"
        + (f", {len(result['retired'])} retired" if result["retired"] else "")
        + _recon_note + _sweep_note + _degraded_note)
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
