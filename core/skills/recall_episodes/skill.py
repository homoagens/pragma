# skills/recall_episodes/skill.py — retrieve relevant episodes from memory
#
# Deterministic counterpart of episode_consolidate: keyword-overlap scoring
# (no LLM, no embeddings) over the episodic store, with a boost for episodes
# born in the same workspace as the current task.
#
# Recall has a deliberate side effect: retrieved episodes get their
# `last_recalled` refreshed and their `salience` reinforced — remembering
# strengthens the memory, which is what will keep it out of the dormant
# zone when forgetting is implemented.

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import config


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    Pure keyword overlap plus a same-workspace boost; falls back to recency
    when the query has no useful tokens or nothing matches.

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
    if not store.is_dir():
        return "(no episodes)"

    episodes: list[tuple[Path, dict]] = []
    for p in sorted(store.glob("ep_*.json")):
        try:
            episodes.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    if not episodes:
        return "(no episodes)"

    qtok = _tokens(query) if query else set()

    def _score(ep: dict) -> int:
        s = len(_tokens(_episode_text(ep)) & qtok) if qtok else 0
        if workspace and ep.get("workspace") == workspace:
            s += boost
        return s

    if qtok or workspace:
        scored = [(p, ep, _score(ep)) for p, ep in episodes]
        matched = [(p, ep, s) for p, ep, s in scored if s > 0]
        if matched:
            matched.sort(key=lambda t: (t[2], t[1].get("ts", "")), reverse=True)
            picked = matched[:k]
        else:
            recent = sorted(episodes, key=lambda t: t[1].get("ts", ""), reverse=True)
            picked = [(p, ep, 0) for p, ep in recent[:k]]
    else:
        recent = sorted(episodes, key=lambda t: t[1].get("ts", ""), reverse=True)
        picked = [(p, ep, 0) for p, ep in recent[:k]]

    if not picked:
        return "(no episodes)"

    lines = []
    now = _now()
    for p, ep, _s in picked:
        # Reinforce on recall — best effort, never let bookkeeping break recall.
        try:
            ep["last_recalled"] = now
            ep["salience"] = min(1.0, float(ep.get("salience", 0.5)) + 0.1)
            p.write_text(json.dumps(ep, indent=2, ensure_ascii=False),
                         encoding="utf-8")
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
        lines.append(head)
        surprises = ep.get("surprises") or []
        if surprises:
            lines.append(f"  surprises: {'; '.join(surprises[:2])}")
    return "\n".join(lines)
