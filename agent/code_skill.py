# agent/code_skill.py — `code` skill for Pragma
#
# Delegates code generation / review / explanation to a dedicated coding model
# (if configured in config) or to the default model.
#
# Configuration (config.py / env):
#   CODING_MODEL       — model name (empty = use DEFAULT_MODEL)
#   CODING_PROVIDER    — "backend" | "openai" (empty = use LLM_PROVIDER)
#   CODING_BASE_URL    — base URL (empty = use LLM_BASE_URL)
#   CODING_API_KEY     — API key (empty = use LLM_API_KEY)
#   CODING_TEMPERATURE — default 0.1 (low for code generation)
#   CODING_MAX_TOKENS  — default 4096
#
# Always returns a string: the requested code (or an error message).

from __future__ import annotations

import config
import llm_client


CODE_SYSTEM_PROMPT = """You are an expert software engineer.
Return ONLY source code — no prose, no explanations, no markdown fences
unless the caller explicitly asks for a full explanation.

Follow these rules:
- Write idiomatic, production-quality code for the requested language.
- If the target language is Python, prefer standard library when possible.
- Include the minimal code necessary to satisfy the request — no placeholder
  comments like "# TODO", no usage examples unless requested.
- If the request is ambiguous, make the most sensible choice and proceed.
- If the request contains "explain" or "review", you MAY include prose.
"""


def code(task: str,
         language: str = "",
         context: str = "",
         mode: str = "generate") -> str:
    """
    [G] Delegate a coding task to a specialized model.

    task     : description of the work (e.g. "write a quicksort in Python")
    language : target language (e.g. "python", "typescript", "rust")
    context  : code or context text (existing file, specs, etc.)
    mode     : "generate" | "review" | "explain" | "refactor" | "fix"

    Uses the CODING_* model if configured, otherwise the default model.
    """
    if not task or not task.strip():
        return "ERROR: code() requires a non-empty `task`."

    # Resolve model + provider: coding-specific → default
    model       = config.CODING_MODEL       or config.DEFAULT_MODEL
    provider    = config.CODING_PROVIDER    or config.LLM_PROVIDER
    base_url    = config.CODING_BASE_URL    or config.LLM_BASE_URL
    api_key     = config.CODING_API_KEY     or config.LLM_API_KEY
    temperature = config.CODING_TEMPERATURE
    max_tokens  = config.CODING_MAX_TOKENS

    # Build the user message
    parts = []
    if mode and mode != "generate":
        parts.append(f"Mode: {mode}")
    if language:
        parts.append(f"Language: {language}")
    parts.append(f"Task: {task.strip()}")
    if context and context.strip():
        parts.append("Context:\n" + context.strip())
    user_message = "\n\n".join(parts)

    try:
        out = llm_client.call_llm(
            messages=[
                {"role": "system", "content": CODE_SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            model       = model,
            temperature = temperature,
            max_tokens  = max_tokens,
            provider    = provider or None,
            base_url    = base_url or None,
            api_key     = api_key  or None,
        )
    except Exception as e:
        return f"ERROR: code() failed — {e}"

    # Strip markdown fences if the model added them despite instructions
    return _strip_code_fences(out)


def _strip_code_fences(text: str) -> str:
    """Remove ``` fences and the opening language line if present."""
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


CODE_SKILLS = {"code": code}
