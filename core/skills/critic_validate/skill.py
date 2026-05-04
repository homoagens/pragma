from __future__ import annotations

import json
from typing import Any

import llm_client
import config
from json_parser import extract_json


_CRITIC_SYSTEM = """You are a critical evaluator for an AI agent.
Given an output and evaluation criteria, assess the output quality.

Respond with ONLY a JSON object:
{
  "verdict":     "PASS" | "WARN" | "FAIL",
  "reason":      "one concise sentence on the overall assessment",
  "suggestions": ["specific improvement if applicable", "..."]
}

Verdict definitions:
- PASS: output fully meets all criteria
- WARN: output meets most criteria but has minor gaps or issues
- FAIL: output fails one or more critical criteria"""


def critic_validate(output: str, criteria: str,
                    model: str = "") -> str:
    """
    [G] Verify an output against semantic criteria via critic LLM.
    Complementary to schema_validate [D] which checks formal structure.
    Returns JSON: {"verdict": "PASS"|"FAIL"|"WARN", "reason": "...", "suggestions": [...]}

    output   : text/JSON to evaluate
    criteria : quality criteria description in natural language
    model    : default config.DEFAULT_MODEL
    """
    user_msg = f"Output:\n{output}\n\nCriteria:\n{criteria}"

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model

    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _CRITIC_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            **kwargs,
        )
        result = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    return json.dumps(result, ensure_ascii=False, indent=2)
