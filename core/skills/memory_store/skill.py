from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import llm_client
from json_parser import extract_json


_MEMORY_STORE_SYSTEM = """You are a memory manager for an AI agent.
Given a piece of content, decide if it is worth saving to persistent memory.
Respond with ONLY a JSON object:
{
  "save":    true or false,
  "key":     "short_snake_case_identifier (max 5 words)",
  "summary": "one concise sentence capturing the essential fact",
  "reason":  "one sentence explaining why you save or skip"
}

Save if: the content contains facts, decisions, errors, user preferences, or context useful in future.
Skip if: the content is trivial, already obvious, purely procedural, or has no future value."""


def memory_store(content: str, memory_path: str = "memory.json",
                 tag: str = "") -> str:
    """
    [H] Save a fact or state to persistent storage.
    Deterministic mechanism: append to a JSON file.
    LLM judgment: decides whether it is worth saving and produces key + summary.

    content     : raw text to evaluate and save
    memory_path : JSON memory file
    tag         : optional category (e.g. "fact", "preference", "error")
    Returns     : "SAVED: key" or "SKIP: reason"
    """
    # 1. Ask the LLM whether it is worth saving [H]
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _MEMORY_STORE_SYSTEM},
                {"role": "user",   "content": f"Content to evaluate:\n{content}"},
            ],
            temperature=0.0,
        )
        decision = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    if not decision.get("save", False):
        reason = decision.get("reason", "not worth saving")
        return f"SKIP: {reason}"

    key     = decision.get("key", "unnamed")
    summary = decision.get("summary", content[:100])

    # 2. Load existing memory [D]
    p = Path(memory_path)
    if p.exists():
        try:
            memory = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            memory = []
    else:
        memory = []

    # 3. Append and write [D]
    entry = {
        "key":     key,
        "summary": summary,
        "tag":     tag,
        "ts":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    memory.append(entry)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        return f"ERROR writing memory: {e}"

    return f"SAVED: {key} — {summary}"
