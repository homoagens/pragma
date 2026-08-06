# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# curator.py — the context curator (knowledge zone of the desk).
#
# "This someone — the curator of the context — is not a mechanical function.
#  It is another invocation of the model, a lighter and dedicated one." It
# receives the task, interrogates memory for candidate fragments, orders them
# from most to least useful, and selects as many as fit.
#
# Here that is a two-stage flow:
#   1. PREFILTER  — deterministic, read-only: gather candidate episodes
#      (active AND dormant) and semantic assertions by keyword overlap. Casts
#      a wide net; NO reinforcement, NO revival happen at this stage.
#   2. CURATE     — one LLM call with a dedicated system prompt: given the
#      task and the numbered candidates, return the ids worth putting on the
#      desk, ordered by usefulness. Pertinence is judged, not keyword-matched.
#   3. APPLY      — only the SELECTED episodes are reinforced (salience +0.1,
#      last_recalled refreshed) and, if dormant, revived. Remembering
#      strengthens the memory — and now "remembering" means the curator
#      judged it relevant, not that a keyword happened to overlap.
#
# The agent never touches raw recall skills: memory reaches the desk only
# through this curator, upstream and automatically.

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import config
import episodes as estore
import llm_client
from json_parser import extract_json


_CURATOR_SYSTEM = """You are the context curator for an AI coding agent.
Before the agent works on a task, you decide which fragments of its memory
belong on its desk — no more, no less.

You receive the TASK and a numbered list of CANDIDATE fragments: past
EPISODES (E1, E2, ...) and learned RULES (L1, L2, ...). Some episodes may be
dormant (faded from disuse); selecting one revives it.

Each episode carries WHEN it happened, relative to TODAY. When the task asks
about a time ("yesterday", "last week", "when did we..."), that stamp decides,
not the wording: an episode that merely mentions the same question is not an
episode that answers it.

Select ONLY the fragments that probably change the quality of the next step —
pertinence, not "it might help". Order the selection from most to least
useful. Be strict: an empty desk beats a noisy one. A dormant fragment is
worth selecting only if it is genuinely relevant to THIS task.

Respond with ONLY a JSON object:
{ "selected": ["E2", "L1", "E5"],   // candidate ids, most useful first
  "reason": "<one short line: why these, or why the desk stays empty>" }

If nothing is truly relevant, return an empty "selected" list."""


# Enforced on the native protocol. A curator reply that fails to parse costs
# the whole curation: the caller falls back to deterministic top-k and the
# model's judgment is discarded for that session.
_CURATOR_SCHEMA = {
    "__name__": "curation",
    "type": "object",
    "properties": {
        "selected": {"type": "array", "items": {"type": "string"}},
        "reason":   {"type": "string"},
    },
    "required": ["selected", "reason"],
    "additionalProperties": False,
}


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _episode_text(ep: dict) -> str:
    return " ".join([
        ep.get("goal", "") or "",
        " ".join(ep.get("keywords", []) or []),
        ep.get("narrative", "") or "",
        " ".join(ep.get("surprises", []) or []),
    ])


# ── Stage 1: prefilter (read-only) ────────────────────────────────────────────

def _episode_candidates(task: str, workspace: str,
                        exclude_ids: set[str] | None = None,
                        require_match: bool = False) -> tuple[list[dict], int]:
    """Candidate episodes for one request, best first, and how many were weighed.

    The second number is what the store actually holds for this request. The
    prefilter is cheap and reads everything; the curator is expensive and sees
    only the best n. Reporting the survivors alone made a store of thirty look
    like a store of ten.

    `exclude_ids` drops episodes before scoring, not after: a live session
    curates once per turn, and an episode already on the desk must not keep
    occupying one of the n slots for the rest of the conversation. Filtering
    afterwards would let the same memory crowd out every newcomer.
    """
    n = getattr(config, "CURATOR_CANDIDATES_EPISODES", 10)
    boost = getattr(config, "EPISODE_WORKSPACE_BOOST", 2)
    skip = exclude_ids or set()
    qtok = _tokens(task)
    scored = []
    for zone, d in (("active", estore.active_dir()),
                    ("dormant", estore.dormant_dir())):
        for p, ep in estore.load(d):
            if ep.get("id") in skip:
                continue
            kw = len(_tokens(_episode_text(ep)) & qtok)
            score = kw + (boost if workspace and ep.get("workspace") == workspace
                          else 0)
            scored.append({"path": p, "ep": ep, "score": score, "kw": kw,
                           "dormant": zone == "dormant"})
    # RELEVANCE IS THE KEYWORDS, NOT THE SCORE. The workspace boost is a
    # tiebreak between episodes that already match; it must not decide WHETHER
    # one matches. It used to: with a boost of 2, every episode in the current
    # workspace scored above zero, so in a store with a single workspace -
    # which is what a personal memory is - everything "matched", the fallback
    # below became unreachable, and the sort fell through to salience. The
    # curator was then handed the ten most IMPORTANT episodes for every
    # question, including the ones about last night.
    matched = [c for c in scored if c["kw"] > 0]
    if matched:
        matched.sort(key=lambda c: (c["score"],
                                    estore.effective_salience(c["ep"]),
                                    c["ep"].get("ts", "")), reverse=True)
        # SOME SLOTS ARE ALWAYS THE LATEST NEWS. A question can be about a
        # subject or about a time, and keywords only find the first kind:
        # "what did we talk about yesterday" shares no words with an episode
        # ABOUT yesterday. These are candidates, not selections - the curator
        # still decides - so the cost of offering them is a few lines of
        # prompt, while the cost of withholding them is a memory that cannot
        # answer the most ordinary question there is.
        r = max(getattr(config, "CURATOR_CANDIDATES_RECENT", 3), 0)
        out = matched[:max(n - r, 0)]
        seen = {id(c["ep"]) for c in out}
        for c in sorted(scored, key=lambda c: c["ep"].get("ts", ""),
                        reverse=True):
            if len(out) >= n:
                break
            if id(c["ep"]) not in seen:
                out.append(c)
                seen.add(id(c["ep"]))
        return out, len(scored)
    # Nothing keyword-relevant — offer the most recent as candidates and let
    # the curator decide (it will usually return an empty desk). One task is
    # worth that call: the opening question of a session often shares no words
    # with anything stored ("what do you know about me?" matches nothing) and
    # is exactly when the past is wanted most.
    #
    # `require_match` refuses that fallback. A live session curates once per
    # turn, and paying an LLM call on every turn to be told the desk is empty
    # is the whole latency budget of a conversation. There the fallback is
    # allowed on the first turn and refused afterwards, so the curator wakes
    # for a genuine change of subject rather than for the passage of time.
    if require_match:
        return [], len(scored)
    scored.sort(key=lambda c: c["ep"].get("ts", ""), reverse=True)
    return scored[:n], len(scored)


def _learning_candidates(task: str,
                         exclude_texts: set[str] | None = None) -> tuple[list[dict], int]:
    m = getattr(config, "CURATOR_CANDIDATES_LEARNINGS", 8)
    skip = exclude_texts or set()
    path = Path(config.LEARNINGS_PATH)
    if not path.exists():
        return [], 0
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    except Exception:
        return [], 0
    qtok = _tokens(task)
    out = []
    pool = 0
    for e in entries:
        if e.get("status", "active") == "retired":
            continue
        pool += 1
        text = e.get("text", "")
        if text in skip:
            continue
        kw = len(_tokens(text) & qtok)
        if kw <= 0:
            continue
        out.append({"entry": e, "score": kw * float(e.get("confidence", 0.5))})
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:m], pool


# ── Stage 2: the curator LLM call ─────────────────────────────────────────────

def _when(ts: str) -> str:
    """"yesterday", "3 days ago", or the plain date. Empty when unparseable.

    A memory has a WHEN, and the curator was never told it. Asked which
    episode bore on "what did we talk about yesterday", it saw ten undated
    cards and no notion of what day it was, so it did the only thing left and
    matched the words - choosing the episode that RECORDED someone asking
    that question over the ones that answered it.

    Stated in relative form because that is the form the question takes.
    "2026-08-05" requires the model to know today's date and subtract;
    "yesterday" is the word the user actually used.
    """
    try:
        when = datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
    except Exception:
        return ""
    days = (datetime.now(timezone.utc).date() - when).days
    if days < 0:
        return str(ts)[:10]
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return str(ts)[:10]


def _episode_card(ref: str, c: dict) -> str:
    ep = c["ep"]
    tag = " [dormant]" if c["dormant"] else ""
    when = _when(ep.get("ts", ""))
    stamp = f" ({when})" if when else ""
    lines = [f"{ref}{tag}{stamp} goal: {ep.get('goal', '')}"]
    nar = _truncate(ep.get("narrative", ""), config.MEMORY_NARRATIVE_CHARS)
    if nar:
        lines.append(f"   what happened: {nar}")
    surprises = ep.get("surprises") or []
    if surprises:
        lines.append(f"   surprises: {'; '.join(surprises[:2])}")
    interp = _truncate(ep.get("interpretation", ""),
                       config.MEMORY_INTERPRETATION_CHARS)
    if interp:
        lines.append(f"   meaning: {interp}")
    return "\n".join(lines)


def _learning_card(ref: str, c: dict) -> str:
    e = c["entry"]
    return (f"{ref} ({e.get('kind', '?')}, confidence "
            f"{float(e.get('confidence', 0.5)):.2f}) {e.get('text', '')}")


def _ask_curator(task: str, eps: list[dict], lns: list[dict],
                 model=None) -> tuple[list[str] | None, str]:
    """Return (ordered selected refs, reason). refs is None on LLM failure."""
    cards = []
    for i, c in enumerate(eps, 1):
        cards.append(_episode_card(f"E{i}", c))
    for i, c in enumerate(lns, 1):
        cards.append(_learning_card(f"L{i}", c))
    # The date anchors the relative stamps on the cards. Without it "yesterday"
    # on a card and "yesterday" in the question are two strings that happen to
    # look alike; with it they are the same day.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = (f"TODAY: {today}\n\nTASK:\n{task}\n\nCANDIDATES:\n"
               + "\n".join(cards))
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _CURATOR_SYSTEM},
                {"role": "user",   "content": payload},
            ],
            model=model,
            temperature=0.0,
            max_tokens=config.MEMORY_MAX_TOKENS,
            template_kwargs=config.memory_template_kwargs("select"),
            response_schema=_CURATOR_SCHEMA,
        )
        data = extract_json(raw)
    except Exception as e:
        # The reason travels with the failure. Swallowing it left the operator
        # with "curator unavailable" and nothing else - and the causes are very
        # different things to do about: an endpoint that dropped, a call that
        # queued behind a campaign until it timed out, a reply truncated before
        # any JSON appeared. Without the cause, all three look like the memory
        # being broken.
        return None, f"{type(e).__name__}: {str(e)[:160]}"
    if not isinstance(data, dict):
        head = " ".join(str(raw).split())[:120]
        return None, f"reply was not JSON: {head}"
    reason = str(data.get("reason", "")).strip()
    sel = data.get("selected", [])
    if not isinstance(sel, list):
        return [], reason
    # Keep only well-formed, existing refs, in the model's order, deduped.
    valid = {f"E{i}" for i in range(1, len(eps) + 1)} | \
            {f"L{i}" for i in range(1, len(lns) + 1)}
    cap = getattr(config, "CURATOR_MAX_FRAGMENTS", 6)
    out, seen = [], set()
    for r in sel:
        r = str(r).strip().upper()
        if r in valid and r not in seen:
            out.append(r)
            seen.add(r)
        if len(out) >= cap:
            break
    return out, reason


def _human_labels(refs: list[str], eps: list[dict], lns: list[dict]) -> list[str]:
    """Short readable labels for the selected refs (for observability)."""
    out = []
    for r in refs:
        if r.startswith("E"):
            i = int(r[1:]) - 1
            if 0 <= i < len(eps):
                dorm = " (dormant→revived)" if eps[i]["dormant"] else ""
                out.append((eps[i]["ep"].get("goal", "") or "episode")[:58] + dorm)
        elif r.startswith("L"):
            i = int(r[1:]) - 1
            if 0 <= i < len(lns):
                out.append("rule: " + (lns[i]["entry"].get("text", "") or "")[:52])
    return out


# ── Stage 3: apply (reinforce/revive selected) + assemble ─────────────────────

def _format_episode(c: dict, workspace: str, revived: bool) -> list[str]:
    ep = c["ep"]
    date = str(ep.get("ts", ""))[:10]
    where = ("this workspace" if workspace and ep.get("workspace") == workspace
             else Path(ep.get("workspace", "")).name or "elsewhere")
    head = f"- ({date}, {where}, {ep.get('outcome', '?')}) {ep.get('goal', '')}"
    if revived:
        head += "  [revived from dormant memory]"
    lines = [head]
    nar = _truncate(ep.get("narrative", ""), config.MEMORY_NARRATIVE_CHARS)
    if nar:
        lines.append(f"  what happened: {nar}")
    surprises = ep.get("surprises") or []
    if surprises:
        lines.append(f"  surprises: {'; '.join(surprises[:2])}")
    interp = _truncate(ep.get("interpretation", ""),
                       config.MEMORY_INTERPRETATION_CHARS)
    if interp:
        lines.append(f"  meaning: {interp}")
    return lines


def _reinforce(c: dict, workspace: str,
               no_reinforce: set[str] | None = None) -> tuple[list[str], bool]:
    """Revive if dormant, reinforce salience; return (formatted lines, revived).
    Best effort — bookkeeping must never break curation.

    `no_reinforce` names episodes this conversation has already reinforced.
    A live session can lose a memory from its context — compaction drops the
    turn it was attached to — and then legitimately need it again. Fetching it
    twice is right; counting it twice is not, or salience would record how
    often a context overflowed rather than what mattered.
    """
    ep = c["ep"]
    revived = False
    try:
        path = c["path"]
        if c["dormant"]:
            path = estore.revive(path, ep)
            revived = True
        if ep.get("id") not in (no_reinforce or set()):
            ep["last_recalled"] = estore.now_iso()
            ep["salience"] = min(1.0, float(ep.get("salience", 0.5)) + 0.1)
        estore.save(path, ep)
    except Exception:
        pass
    return _format_episode(c, workspace, revived), revived


def _assemble(refs: list[str], eps: list[dict], lns: list[dict],
              workspace: str, no_reinforce: set[str] | None = None) -> str:
    if not refs:
        return ""
    lines = [
        "[Relevant memory — fragments the context curator selected for this "
        "task; notes and rules from past sessions, may be outdated, verify "
        "against the actual files]"
    ]
    for r in refs:
        if r.startswith("E"):
            idx = int(r[1:]) - 1
            if 0 <= idx < len(eps):
                block, _ = _reinforce(eps[idx], workspace, no_reinforce)
                lines.extend(block)
        elif r.startswith("L"):
            idx = int(r[1:]) - 1
            if 0 <= idx < len(lns):
                e = lns[idx]["entry"]
                lines.append(f"- (learned rule · {e.get('kind', '?')}) "
                             f"{e.get('text', '')}")
    return "\n".join(lines)


def _fallback(eps: list[dict], lns: list[dict], workspace: str,
              no_reinforce: set[str] | None = None) -> tuple[str, list[str]]:
    """Deterministic top-k when the curator LLM call fails — never lose the
    context to a curator error. Returns (block, the refs it used)."""
    cap = getattr(config, "CURATOR_MAX_FRAGMENTS", 6)
    refs = [f"E{i}" for i in range(1, len(eps) + 1)]
    refs += [f"L{i}" for i in range(1, len(lns) + 1)]
    refs = refs[:cap]
    return _assemble(refs, eps, lns, workspace, no_reinforce), refs


def _placed(refs: list[str], eps: list[dict],
            lns: list[dict]) -> tuple[list[str], list[str]]:
    """The episode ids and rule texts a set of refs actually resolves to.

    A caller that curates repeatedly needs to know what reached the desk, not
    what was offered: the refs are positions in this call's candidate list and
    mean nothing once the list is rebuilt on the next turn.
    """
    ids, texts = [], []
    for r in refs or []:
        try:
            idx = int(r[1:]) - 1
        except ValueError:
            continue
        if r.startswith("E") and 0 <= idx < len(eps):
            ids.append(eps[idx]["ep"].get("id", ""))
        elif r.startswith("L") and 0 <= idx < len(lns):
            texts.append(lns[idx]["entry"].get("text", ""))
    return [i for i in ids if i], [t for t in texts if t]


# ── Public API ────────────────────────────────────────────────────────────────

def curate_knowledge_detailed(task: str, workspace: str = "", model=None,
                              exclude_ids: set[str] | None = None,
                              exclude_rules: set[str] | None = None,
                              require_match: bool = False,
                              no_reinforce: set[str] | None = None) -> dict:
    """Compose the knowledge zone and report what the curator did.

    `exclude_ids` / `exclude_rules` name what the caller already has in front
    of the agent. A batch run passes neither: it curates once, for one task.
    A live session passes what earlier turns put on the desk, so the curator
    is asked only about what is NEW — which keeps the same memory from being
    pasted into the conversation twenty times, and keeps recall from
    reinforcing one episode once per turn instead of once per session.

    Returns a dict:
      { "block":    "<knowledge zone markdown, or ''>",
        "n_ep":     candidate episodes considered,
        "n_ln":     candidate rules considered,
        "selected": [human labels of chosen fragments],
        "episode_ids": [ids actually placed on the desk],
        "rule_texts":  [rule texts actually placed on the desk],
        "reason":   "<curator's one-line justification>",
        "fallback": bool,   # curator LLM failed → deterministic top-k
        "empty":    bool }  # nothing relevant, or the curator chose an empty desk
    """
    info = {"block": "", "n_ep": 0, "n_ln": 0, "pool_ep": 0, "pool_ln": 0,
            "selected": [],
            "episode_ids": [], "rule_texts": [],
            "reason": "", "fallback": False, "empty": False}
    if not task or not task.strip():
        info["empty"] = True
        return info
    eps, pool_ep = _episode_candidates(task, workspace, exclude_ids,
                                       require_match)
    lns, pool_ln = _learning_candidates(task, exclude_rules)
    info["n_ep"], info["n_ln"] = len(eps), len(lns)
    info["pool_ep"], info["pool_ln"] = pool_ep, pool_ln
    if not eps and not lns:
        info["empty"] = True
        return info

    if not getattr(config, "CURATOR_ENABLED", True):
        info["block"], refs = _fallback(eps, lns, workspace, no_reinforce)
        info["episode_ids"], info["rule_texts"] = _placed(refs, eps, lns)
        info["fallback"] = True
        return info

    refs, reason = _ask_curator(task, eps, lns, model=model)
    if refs is None:                       # LLM failed → deterministic fallback
        info["reason"] = reason            # perche', non solo che
        info["block"], refs = _fallback(eps, lns, workspace, no_reinforce)
        info["episode_ids"], info["rule_texts"] = _placed(refs, eps, lns)
        info["fallback"] = True
        return info
    info["reason"] = reason
    info["selected"] = _human_labels(refs, eps, lns)
    info["episode_ids"], info["rule_texts"] = _placed(refs, eps, lns)
    info["block"] = _assemble(refs, eps, lns, workspace,
                              no_reinforce)          # [] → "" (empty desk)
    info["empty"] = not info["block"]
    return info


def curate_knowledge(task: str, workspace: str = "", model=None) -> str:
    """Thin wrapper: return only the assembled knowledge-zone block."""
    return curate_knowledge_detailed(task, workspace, model)["block"]
