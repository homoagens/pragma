# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# skills/recall_episodes/skill.py — retrieve relevant episodes from memory
#
# Deterministic counterpart of episode_consolidate: keyword-overlap scoring
# (no LLM, no embeddings) over the ACTIVE zone of the episodic store, with
# a boost for episodes born in the same workspace as the current task.
# Ties are broken by effective salience (see core/episodes.py): between two
# equally relevant episodes, the more alive one wins.
#
# Recall has two deliberate side effects, both from the forgetting model:
#   - retrieved episodes get `last_recalled` refreshed and `salience`
#     reinforced — remembering strengthens the memory and resets its decay;
#   - when the active zone can't fill the requested slots, the DORMANT zone
#     is searched by keyword relevance, and any hit is REVIVED: moved back
#     to the active zone with its age reset. A fading memory that becomes
#     relevant again returns to availability — forgetting is reversible.

from __future__ import annotations

import re
from pathlib import Path

import config
import episodes as estore


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _episode_text(ep: dict) -> str:
    return " ".join([
        ep.get("goal", "") or "",
        " ".join(ep.get("keywords", []) or []),
        ep.get("narrative", "") or "",
        " ".join(ep.get("surprises", []) or []),
    ])


def recall_episodes(query: str = "", workspace: str = "", top_k: int = 0,
                    store_dir: str = "") -> str:
    """
    [D] Retrieve the most relevant episodes from the episodic memory store.

    Pure keyword overlap plus a same-workspace boost over the active zone;
    falls back to recency when nothing matches. When fewer than top_k
    keyword matches exist, the dormant zone is searched too and matching
    episodes are revived (moved back to active, age reset).

    query      : free text describing the upcoming task. Empty = most recent.
    workspace  : current working directory; episodes from the same workspace
                 get a score bonus (config.EPISODE_WORKSPACE_BOOST).
    top_k      : how many episodes to return. 0 = config.EPISODES_RECALL_TOP_K.
    store_dir  : episode store override. Default config.EPISODES_DIR.
    Returns    : formatted episodes (compact, one block per episode) or
                 "(no episodes)".
    """
    k = top_k if top_k > 0 else getattr(config, "EPISODES_RECALL_TOP_K", 3)
    boost = getattr(config, "EPISODE_WORKSPACE_BOOST", 2)
    store = Path(store_dir) if store_dir else Path(config.EPISODES_DIR)

    active = estore.load(estore.active_dir(store))
    qtok = _tokens(query) if query else set()

    def _kw(ep: dict) -> int:
        """TRUE keyword overlap — the workspace boost deliberately excluded."""
        return len(_tokens(_episode_text(ep)) & qtok) if qtok else 0

    def _score(ep: dict) -> int:
        s = _kw(ep)
        if workspace and ep.get("workspace") == workspace:
            s += boost
        return s

    # Tuples are (path, episode, total_score, keyword_score).
    picked: list[tuple] = []
    if active:
        if qtok or workspace:
            scored = [(p, ep, _score(ep), _kw(ep)) for p, ep in active]
            matched = [t for t in scored if t[2] > 0]
            if matched:
                matched.sort(key=lambda t: (t[2],
                                            estore.effective_salience(t[1]),
                                            t[1].get("ts", "")),
                             reverse=True)
                picked = matched[:k]
            else:
                recent = sorted(active, key=lambda t: t[1].get("ts", ""),
                                reverse=True)
                picked = [(p, ep, 0, 0) for p, ep in recent[:k]]
        else:
            recent = sorted(active, key=lambda t: t[1].get("ts", ""),
                            reverse=True)
            picked = [(p, ep, 0, 0) for p, ep in recent[:k]]

    # ── Dormant revival ──
    # Only a real keyword match revives (relevance brings memories back;
    # mere recency does not). Crucially, the "did the active zone answer
    # the query?" test counts TRUE keyword matches only: the workspace
    # boost makes every local episode score > 0, and counting those would
    # keep the dormant zone forever unreachable once the active zone holds
    # k+ episodes (field-found bug). A relevant dormant episode then
    # DISPLACES boost-only actives from the result — relevance outranks
    # mere locality.
    revived_ids: set = set()
    if qtok:
        need = k - sum(1 for t in picked if t[3] > 0)
        if need > 0:
            dorm = estore.load(estore.dormant_dir(store))
            dscored = [(p, ep, len(_tokens(_episode_text(ep)) & qtok))
                       for p, ep in dorm]
            dmatch = [t for t in dscored if t[2] > 0]
            dmatch.sort(key=lambda t: (t[2], t[1].get("ts", "")), reverse=True)
            revived: list[tuple] = []
            for p, ep, s in dmatch[:need]:
                try:
                    newp = estore.revive(p, ep, store)
                except Exception:
                    continue
                revived.append((newp, ep, s, s))
                revived_ids.add(ep.get("id"))
            if revived:
                keyword_hits = [t for t in picked if t[3] > 0]
                boost_only   = [t for t in picked if t[3] == 0]
                picked = (keyword_hits + revived + boost_only)[:k]

    if not picked:
        return "(no episodes)"

    lines = []
    now = estore.now_iso()
    for p, ep, _s, _kw_s in picked:
        # Reinforce on recall — best effort, never let bookkeeping break recall.
        try:
            ep["last_recalled"] = now
            ep["salience"] = min(1.0, float(ep.get("salience", 0.5)) + 0.1)
            estore.save(p, ep)
        except Exception:
            pass

        date = str(ep.get("ts", ""))[:10]
        if workspace and ep.get("workspace") == workspace:
            where = "this workspace"
        else:
            where = Path(ep.get("workspace", "")).name or "elsewhere"
        head = f"- ({date}, {where}, {ep.get('outcome', '?')}) {ep.get('goal', '')}"
        interp = (ep.get("interpretation") or "").strip()
        if interp:
            head += f" — {interp}"
        if ep.get("id") in revived_ids:
            head += "  [revived from dormant memory]"
        lines.append(head)
        surprises = ep.get("surprises") or []
        if surprises:
            lines.append(f"  surprises: {'; '.join(surprises[:2])}")
    return "\n".join(lines)
