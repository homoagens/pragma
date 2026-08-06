# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config
import llm_client
from json_parser import extract_json


_REFLECT_SYSTEM = """You are a reflection assistant for an AI coding agent.
You receive a transcript of a recently completed task and extract DURABLE
learnings — facts and patterns that will help on future tasks.

Respond with ONLY a JSON object of this exact shape:
{
  "lessons":    [ "short factual sentence ...", ... ],
  "patterns":   [ "tool X should be preferred over Y when ...", ... ],
  "user_prefs": [ "the user wants ...", ... ],
  "mistakes":   [ "I tried X and it failed because ...", ... ]
}

Rules:
- Keep each item under 200 characters.
- Skip arrays that have nothing worth recording (return them empty).
- NEVER record one-off task content (e.g. "I wrote a script for the solar system")
  — only generalizable insight.
- NEVER duplicate items already obvious from the agent's tool list.
- Quality over quantity. 0-3 items per array is fine."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_store(path: Path) -> dict:
    if not path.exists():
        return {"entries": [], "created_at": _now()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "entries" not in data:
            data["entries"] = []
        return data
    except Exception:
        return {"entries": [], "created_at": _now()}


def _save_store(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def session_reflect_detailed(transcript: str = "",
                             store_path: str = "",
                             label: str = "") -> dict:
    """
    Internal version of session_reflect that returns a structured result
    instead of just the summary string. Used by the server's reflection
    worker to surface the specific entries it added to the UI (so the
    user can expand the "📚 Saved 2 lessons" indicator and see what they
    actually contain).

    Returns:
      { "status":  "ok" | "skip" | "error",
        "summary": "<short human label, same as session_reflect() str>",
        "added":   [ {kind, text, label, ts}, ... ]   # newly persisted only
      }
    """
    if not transcript or not transcript.strip():
        return {"status": "error", "summary": "ERROR: transcript is empty", "added": []}

    default_target = Path(config.LEARNINGS_PATH)
    target = Path(store_path) if store_path else default_target
    # A caller that means "store it over here" passes a folder. Writing to a
    # folder raises Permission denied on Windows, which names the wrong cause
    # and sent one session hunting for a rights problem that did not exist.
    if target.is_dir():
        target = target / default_target.name
    if target != default_target and target.parent != default_target.parent:
        # Learnings written outside the configured store are never read back:
        # the curator only ever looks at config.LEARNINGS_PATH. Better to
        # refuse than to leave an orphan file that looks like a success.
        return {"status": "error", "added": [], "summary": (
            f"ERROR: refused — learnings would go to {target}, but memory "
            f"reads {default_target}. Anything written elsewhere is never "
            f"recalled. Call session_reflect without store_path.")}

    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _REFLECT_SYSTEM},
                {"role": "user",
                 "content": f"Task transcript:\n\n{transcript}"},
            ],
            temperature=0.0,
            max_tokens=config.MEMORY_MAX_TOKENS,
            template_kwargs=config.memory_template_kwargs("write"),
        )
        result = extract_json(raw)
    except Exception as e:
        return {"status": "error",
                "summary": f"ERROR: reflect LLM call failed — {e}",
                "added": []}

    buckets = {
        "lessons":    result.get("lessons", []) or [],
        "patterns":   result.get("patterns", []) or [],
        "user_prefs": result.get("user_prefs", []) or [],
        "mistakes":   result.get("mistakes", []) or [],
    }
    if sum(len(v) for v in buckets.values()) == 0:
        return {"status": "skip",
                "summary": "SKIP: nothing worth learning from this session",
                "added": []}

    store = _load_store(target)
    ts    = _now()
    added: list[dict] = []
    for kind, items in buckets.items():
        for it in items:
            if not isinstance(it, str) or not it.strip():
                continue
            text = it.strip()[:300]
            # Cheap dedup: skip if an entry with the same text already exists.
            if any(e.get("text") == text for e in store["entries"]):
                continue
            entry = {"kind": kind, "text": text, "label": label or "", "ts": ts}
            store["entries"].append(entry)
            added.append(entry)

    try:
        _save_store(target, store)
    except Exception as e:
        return {"status": "error",
                "summary": f"ERROR writing learnings store: {e}",
                "added": []}

    # Report counts of what was actually persisted (post-dedup), not what
    # the model proposed.
    counts = {k: 0 for k in buckets}
    for a in added:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
    summary = (
        f"OK: saved learnings to {target} "
        f"(lessons={counts['lessons']} patterns={counts['patterns']} "
        f"user_prefs={counts['user_prefs']} mistakes={counts['mistakes']})"
    )
    if not added:
        # Everything the model proposed was a duplicate.
        return {"status": "skip",
                "summary": "SKIP: all proposed learnings were duplicates",
                "added": []}
    return {"status": "ok", "summary": summary, "added": added}


def session_reflect(transcript: str = "",
                    store_path: str = "",
                    label: str = "") -> str:
    """
    [H] Run a reflection pass on a completed task and persist durable learnings
    to the cross-thread learnings store.

    transcript : the task narrative (thoughts + actions + observations).
                 If empty, the skill returns ERROR (the caller must provide it).
    store_path : LEAVE THIS EMPTY. The default is the one store memory reads;
                 anything written elsewhere is never recalled, so a different
                 path is refused rather than silently orphaned. It exists for
                 the server's own reflection worker.
    label      : optional short tag, attached to every entry produced this round.

    Returns "OK: saved N learnings (lessons=a patterns=b user_prefs=c mistakes=d)"
    or "ERROR: ..." or "SKIP: nothing to learn" if the model returns empty arrays.

    This is the string-returning wrapper expected by the agent skill protocol.
    For structured output (used by the server's background worker to show the
    added entries in the UI) call session_reflect_detailed() directly.
    """
    return session_reflect_detailed(transcript, store_path, label)["summary"]
