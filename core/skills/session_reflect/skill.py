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


def session_reflect(transcript: str = "",
                    store_path: str = "",
                    label: str = "") -> str:
    """
    [H] Run a reflection pass on a completed task and persist durable learnings
    to the cross-thread learnings store.

    transcript : the task narrative (thoughts + actions + observations).
                 If empty, the skill returns ERROR (the caller must provide it).
    store_path : where to persist. Defaults to config.LEARNINGS_PATH.
    label      : optional short tag, attached to every entry produced this round.

    Returns "OK: saved N learnings (lessons=a patterns=b user_prefs=c mistakes=d)"
    or "ERROR: ..." or "SKIP: nothing to learn" if the model returns empty arrays.
    """
    if not transcript or not transcript.strip():
        return "ERROR: transcript is empty"

    target = Path(store_path) if store_path else Path(config.LEARNINGS_PATH)

    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _REFLECT_SYSTEM},
                {"role": "user",
                 "content": f"Task transcript:\n\n{transcript}"},
            ],
            temperature=0.0,
            max_tokens=config.SKILL_MAX_TOKENS,
        )
        result = extract_json(raw)
    except Exception as e:
        return f"ERROR: reflect LLM call failed — {e}"

    buckets = {
        "lessons":    result.get("lessons", []) or [],
        "patterns":   result.get("patterns", []) or [],
        "user_prefs": result.get("user_prefs", []) or [],
        "mistakes":   result.get("mistakes", []) or [],
    }
    total = sum(len(v) for v in buckets.values())
    if total == 0:
        return "SKIP: nothing worth learning from this session"

    store = _load_store(target)
    ts    = _now()
    for kind, items in buckets.items():
        for it in items:
            if not isinstance(it, str) or not it.strip():
                continue
            text = it.strip()[:300]
            # Cheap dedup: skip if an entry with the same text already exists.
            if any(e.get("text") == text for e in store["entries"]):
                continue
            store["entries"].append({
                "kind":  kind,
                "text":  text,
                "label": label or "",
                "ts":    ts,
            })

    try:
        _save_store(target, store)
    except Exception as e:
        return f"ERROR writing learnings store: {e}"

    saved = (
        f"OK: saved learnings to {target} "
        f"(lessons={len(buckets['lessons'])} patterns={len(buckets['patterns'])} "
        f"user_prefs={len(buckets['user_prefs'])} mistakes={len(buckets['mistakes'])})"
    )
    return saved
