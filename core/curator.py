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

Select ONLY the fragments that probably change the quality of the next step —
pertinence, not "it might help". Order the selection from most to least
useful. Be strict: an empty desk beats a noisy one. A dormant fragment is
worth selecting only if it is genuinely relevant to THIS task.

Respond with ONLY a JSON object:
{ "selected": ["E2", "L1", "E5"],   // candidate ids, most useful first
  "reason": "<one short line: why these, or why the desk stays empty>" }

If nothing is truly relevant, return an empty "selected" list."""


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

def _episode_candidates(task: str, workspace: str) -> list[dict]:
    n = getattr(config, "CURATOR_CANDIDATES_EPISODES", 10)
    boost = getattr(config, "EPISODE_WORKSPACE_BOOST", 2)
    qtok = _tokens(task)
    scored = []
    for zone, d in (("active", estore.active_dir()),
                    ("dormant", estore.dormant_dir())):
        for p, ep in estore.load(d):
            kw = len(_tokens(_episode_text(ep)) & qtok)
            score = kw + (boost if workspace and ep.get("workspace") == workspace
                          else 0)
            scored.append({"path": p, "ep": ep, "score": score, "kw": kw,
                           "dormant": zone == "dormant"})
    matched = [c for c in scored if c["score"] > 0]
    if matched:
        matched.sort(key=lambda c: (c["score"],
                                    estore.effective_salience(c["ep"]),
                                    c["ep"].get("ts", "")), reverse=True)
        return matched[:n]
    # Nothing keyword-relevant — offer the most recent as candidates and let
    # the curator decide (it will usually return an empty desk).
    scored.sort(key=lambda c: c["ep"].get("ts", ""), reverse=True)
    return scored[:n]


def _learning_candidates(task: str) -> list[dict]:
    m = getattr(config, "CURATOR_CANDIDATES_LEARNINGS", 8)
    path = Path(config.LEARNINGS_PATH)
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    except Exception:
        return []
    qtok = _tokens(task)
    out = []
    for e in entries:
        if e.get("status", "active") == "retired":
            continue
        text = e.get("text", "")
        kw = len(_tokens(text) & qtok)
        if kw <= 0:
            continue
        out.append({"entry": e, "score": kw * float(e.get("confidence", 0.5))})
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:m]


# ── Stage 2: the curator LLM call ─────────────────────────────────────────────

def _episode_card(ref: str, c: dict) -> str:
    ep = c["ep"]
    tag = " [dormant]" if c["dormant"] else ""
    lines = [f"{ref}{tag} goal: {ep.get('goal', '')}"]
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
    payload = f"TASK:\n{task}\n\nCANDIDATES:\n" + "\n".join(cards)
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _CURATOR_SYSTEM},
                {"role": "user",   "content": payload},
            ],
            model=model,
            temperature=0.0,
            max_tokens=getattr(config, "SKILL_MAX_TOKENS", 2048),
        )
        data = extract_json(raw)
    except Exception:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
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


def _reinforce(c: dict, workspace: str) -> tuple[list[str], bool]:
    """Revive if dormant, reinforce salience; return (formatted lines, revived).
    Best effort — bookkeeping must never break curation."""
    ep = c["ep"]
    revived = False
    try:
        path = c["path"]
        if c["dormant"]:
            path = estore.revive(path, ep)
            revived = True
        ep["last_recalled"] = estore.now_iso()
        ep["salience"] = min(1.0, float(ep.get("salience", 0.5)) + 0.1)
        estore.save(path, ep)
    except Exception:
        pass
    return _format_episode(c, workspace, revived), revived


def _assemble(refs: list[str], eps: list[dict], lns: list[dict],
              workspace: str) -> str:
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
                block, _ = _reinforce(eps[idx], workspace)
                lines.extend(block)
        elif r.startswith("L"):
            idx = int(r[1:]) - 1
            if 0 <= idx < len(lns):
                e = lns[idx]["entry"]
                lines.append(f"- (learned rule · {e.get('kind', '?')}) "
                             f"{e.get('text', '')}")
    return "\n".join(lines)


def _fallback(eps: list[dict], lns: list[dict], workspace: str) -> str:
    """Deterministic top-k when the curator LLM call fails — never lose the
    context to a curator error."""
    cap = getattr(config, "CURATOR_MAX_FRAGMENTS", 6)
    refs = [f"E{i}" for i in range(1, len(eps) + 1)]
    refs += [f"L{i}" for i in range(1, len(lns) + 1)]
    return _assemble(refs[:cap], eps, lns, workspace)


# ── Public API ────────────────────────────────────────────────────────────────

def curate_knowledge_detailed(task: str, workspace: str = "", model=None) -> dict:
    """Compose the knowledge zone and report what the curator did.

    Returns a dict:
      { "block":    "<knowledge zone markdown, or ''>",
        "n_ep":     candidate episodes considered,
        "n_ln":     candidate rules considered,
        "selected": [human labels of chosen fragments],
        "reason":   "<curator's one-line justification>",
        "fallback": bool,   # curator LLM failed → deterministic top-k
        "empty":    bool }  # nothing relevant, or the curator chose an empty desk
    """
    info = {"block": "", "n_ep": 0, "n_ln": 0, "selected": [],
            "reason": "", "fallback": False, "empty": False}
    if not task or not task.strip():
        info["empty"] = True
        return info
    eps = _episode_candidates(task, workspace)
    lns = _learning_candidates(task)
    info["n_ep"], info["n_ln"] = len(eps), len(lns)
    if not eps and not lns:
        info["empty"] = True
        return info

    if not getattr(config, "CURATOR_ENABLED", True):
        info["block"] = _fallback(eps, lns, workspace)
        info["fallback"] = True
        return info

    refs, reason = _ask_curator(task, eps, lns, model=model)
    if refs is None:                       # LLM failed → deterministic fallback
        info["block"] = _fallback(eps, lns, workspace)
        info["fallback"] = True
        return info
    info["reason"] = reason
    info["selected"] = _human_labels(refs, eps, lns)
    info["block"] = _assemble(refs, eps, lns, workspace)  # [] → "" (empty desk)
    info["empty"] = not info["block"]
    return info


def curate_knowledge(task: str, workspace: str = "", model=None) -> str:
    """Thin wrapper: return only the assembled knowledge-zone block."""
    return curate_knowledge_detailed(task, workspace, model)["block"]
