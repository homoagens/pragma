from __future__ import annotations

import json
from pathlib import Path

import llm_client
from json_parser import extract_json


_MEMORY_RETRIEVE_SYSTEM = """You are a memory retrieval assistant for an AI agent.
Given a query and a numbered list of memory entries, return the indices of the entries
most semantically relevant to the query.

Respond with ONLY a JSON object:
{
  "indices": [0, 2, ...],
  "reason": "one sentence explaining the selection"
}

Rules:
- indices is a list of integers (0-based) of the relevant entries, in relevance order
- return an empty list if nothing is relevant
- do not include entries that are only loosely related
- respect the top_k limit"""


def memory_retrieve(query: str, memory_path: str = "memory.json",
                    top_k: int = 5) -> str:
    """
    [H] Retrieve memories relevant to a query.
    Deterministic mechanism: reads the JSON file.
    LLM judgment: selects the top_k most semantically relevant results.

    query       : what is being searched for
    memory_path : JSON memory file
    top_k       : how many results to return
    Returns     : formatted entries or "NO RESULTS" / "MEMORY EMPTY"
    """
    # 1. Load memory [D]
    p = Path(memory_path)
    if not p.exists():
        return "MEMORY EMPTY"
    try:
        memory = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return f"ERROR reading memory: {e}"

    if not memory:
        return "MEMORY EMPTY"

    # 2. Build the numbered list for the LLM [D]
    numbered = "\n".join(
        f"[{i}] key={e.get('key','')} tag={e.get('tag','')} | {e.get('summary','')}"
        for i, e in enumerate(memory)
    )

    user_msg = (
        f"Query: {query}\n"
        f"top_k: {top_k}\n\n"
        f"Memory entries:\n{numbered}"
    )

    # 3. Ask the LLM which entries are relevant [H]
    import config as _cfg
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _MEMORY_RETRIEVE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=_cfg.SKILL_MAX_TOKENS,
        )
        result = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    indices = result.get("indices", [])
    reason  = result.get("reason", "")

    if not indices:
        return f"NO RESULTS: {reason}"

    # 4. Return the selected entries [D]
    selected = []
    for i in indices[:top_k]:
        if 0 <= i < len(memory):
            e = memory[i]
            selected.append(
                f"[{e.get('key','')}] ({e.get('tag','')} | {e.get('ts','')})\n"
                f"  {e.get('summary','')}"
            )

    return "\n\n".join(selected)
