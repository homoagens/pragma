from __future__ import annotations

import json
import re
from pathlib import Path

import config


_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s) if len(w) > 2}


def _score(entry_text: str, query_tokens: set[str]) -> int:
    """Cheap keyword overlap score. Higher is better."""
    if not query_tokens:
        return 0
    et = _tokens(entry_text)
    return len(et & query_tokens)


def recall_learnings(query: str = "",
                     top_k: int = 0,
                     store_path: str = "",
                     kinds: str = "") -> str:
    """
    [D] Retrieve the most relevant learnings from the cross-thread store.

    Pure keyword overlap (no LLM call, no embeddings). Fast, deterministic,
    sufficient for stores up to a few thousand entries. Falls back to recency
    when query has no useful tokens.

    query      : free text describing the upcoming task. Empty string returns
                 the most recent entries.
    top_k      : how many entries to return. 0 = config.LEARNINGS_RECALL_TOP_K.
    store_path : override. Default config.LEARNINGS_PATH.
    kinds      : optional comma-separated filter, e.g. "user_prefs,patterns".
                 Empty means all kinds.
    Returns    : formatted entries (one per line) or "(no learnings)".
    """
    k = top_k if top_k > 0 else getattr(config, "LEARNINGS_RECALL_TOP_K", 5)
    target = Path(store_path) if store_path else Path(config.LEARNINGS_PATH)
    if not target.exists():
        return "(no learnings)"

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as e:
        return f"ERROR reading learnings: {e}"

    entries = data.get("entries", [])
    if not entries:
        return "(no learnings)"

    if kinds.strip():
        allowed = {k.strip() for k in kinds.split(",") if k.strip()}
        entries = [e for e in entries if e.get("kind") in allowed]
        if not entries:
            return "(no learnings of requested kinds)"

    # v2 entries carry a status: assertions retired by repeated contradictions
    # stay in the store (provenance) but leave active recall. Legacy entries
    # have no status and count as active.
    entries = [e for e in entries if e.get("status", "active") != "retired"]
    if not entries:
        return "(no learnings)"

    qtok = _tokens(query) if query else set()

    if qtok:
        # Sort by confidence-weighted score desc, then by recency desc.
        # Legacy entries without a confidence field weigh 0.5 (neutral).
        scored = [(e, _score(e.get("text", ""), qtok) * e.get("confidence", 0.5))
                  for e in entries]
        scored = [(e, s) for e, s in scored if s > 0]
        if not scored:
            # Nothing matched: fall back to most recent.
            picked = sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)[:k]
        else:
            scored.sort(key=lambda t: (t[1], t[0].get("ts", "")), reverse=True)
            picked = [e for e, _ in scored[:k]]
    else:
        picked = sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)[:k]

    if not picked:
        return "(no learnings)"

    lines = []
    for e in picked:
        kind  = e.get("kind", "?")
        text  = e.get("text", "")
        label = e.get("label", "")
        suffix = f"  [{label}]" if label else ""
        lines.append(f"- ({kind}) {text}{suffix}")
    return "\n".join(lines)
