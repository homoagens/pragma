# skills/g.py — Delegable skills [G]
#
# "Granted" — the operation is delegated to a specialized external entity.
# The calling agent produces the structured input; the external party does the work.
# Explicit responsibility boundary: if the result is wrong,
# the input provided to the external party was insufficient (recursive corollary).
#
# Skills covered (7):
#   llm_invoke, vision_interpret, web_search,
#   context_compress, call_agent, todo_execute, critic_validate

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Callable, Optional

import llm_client
import config
from json_parser import extract_json


# ─────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────

def llm_invoke(system_prompt: str, user_message: str,
               model: str = "", temperature: float = -1.0,
               max_tokens: int = 0) -> str:
    """
    [G] Textual LLM call as a first-class skill.
    Direct wrapper around llm_client.call_llm() with a uniform interface.
    Returns the response text or an error message.

    system_prompt : system instructions
    user_message  : user message
    model         : default config.DEFAULT_MODEL
    temperature   : default config.DEFAULT_TEMPERATURE  (-1 = use default)
    max_tokens    : default config.MAX_TOKENS  (0 = use default)
    """
    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if temperature >= 0.0:
        kwargs["temperature"] = temperature
    if max_tokens > 0:
        kwargs["max_tokens"] = max_tokens

    try:
        return llm_client.call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            **kwargs,
        )
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"


def vision_interpret(image_path: str, question: str,
                     model: str = "", detail: str = "auto") -> str:
    """
    [G] Multimodal LLM call: image → textual interpretation.
    Distinct signature from llm_invoke because the payload differs (base64 image).

    image_path : local path of the image (PNG/JPG/WEBP/GIF)
    question   : what to interpret or extract from the image
    model      : vision-capable model (default config.DEFAULT_MODEL)
    detail     : "low" | "high" | "auto" (token detail level)
    """
    p = Path(image_path)
    if not p.exists():
        return f"ERROR: image not found — {image_path}"

    try:
        raw_bytes = p.read_bytes()
        b64       = base64.b64encode(raw_bytes).decode()
        mime      = mimetypes.guess_type(str(p))[0] or "image/png"
    except OSError as e:
        return f"ERROR reading image: {e}"

    # OpenAI vision-style payload
    content = [
        {
            "type": "image_url",
            "image_url": {
                "url":    f"data:{mime};base64,{b64}",
                "detail": detail,
            },
        },
        {"type": "text", "text": question},
    ]

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model

    try:
        return llm_client.call_llm(
            messages=[{"role": "user", "content": content}],
            **kwargs,
        )
    except Exception as e:
        msg = str(e)
        if "422" in msg:
            return (
                "ERROR: the backend does not support multimodal calls. "
                "Use a vision-capable model (e.g. gpt-4o, claude-3) "
                f"and verify that the endpoint accepts image_url payloads. [{msg}]"
            )
        return f"ERROR: LLM vision call failed — {e}"


# ─────────────────────────────────────────────────────────────
# INFORMATION RETRIEVAL
# ─────────────────────────────────────────────────────────────

def web_search(query: str, num_results: int = 10,
               engine: str = "duckduckgo") -> str:
    """
    [G] Query a search engine. Returns ranked snippets and URLs.
    engine : "duckduckgo" (default, no API key required) | "serper" | "brave"

    Note: optimal query formulation may require an upstream llm_invoke()
    by the calling agent (judgment [H]).
    """
    if engine == "duckduckgo":
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                return (
                    "ERROR: DDGS library not installed. "
                    "Run: pip install ddgs"
                )
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results))
        except Exception as e:
            return f"ERROR: DuckDuckGo search failed — {e}"

    elif engine == "serper":
        api_key = getattr(config, "SERPER_API_KEY", "")
        if not api_key:
            return "ERROR: SERPER_API_KEY not configured in config.py"
        try:
            import requests
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num_results},
                timeout=15,
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
            results = [
                {"title": r.get("title", ""), "href": r.get("link", ""),
                 "body": r.get("snippet", "")}
                for r in organic
            ]
        except Exception as e:
            return f"ERROR: Serper search failed — {e}"

    else:
        return f"ERROR: engine '{engine}' not supported. Use 'duckduckgo' or 'serper'."

    if not results:
        return "NO RESULTS"

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.get('title', '')}] {r.get('href', '')}")
        body = r.get("body", "")
        if body:
            lines.append(f"   {body[:200]}")
        lines.append("")

    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────
# MEMORY & STATE
# ─────────────────────────────────────────────────────────────

def context_compress(messages: list[dict], label: str = "context",
                     model: str = "") -> list[dict]:
    """
    [G] Summarize and compress context when approaching the limit.
    Delegates to memory.compress() which uses a single LLM call to summarize.
    Returns the compressed message list (same structure, fewer elements).

    messages : list [{role, content}] in OpenAI style
    label    : label for the compression log
    model    : model used for the summary (default config.DEFAULT_MODEL)
    """
    import memory

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model

    # threshold=0 forces compression regardless of message count
    return memory.compress(messages, threshold=0, context=label, **kwargs)


# ─────────────────────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────────────────────

def call_agent(agent_name: str, task: str,
               input_data: str = "", endpoint: str = "") -> str:
    """
    [G] Delegate a task to a specialized sub-agent.
    HTTP mode: POST to <endpoint>/run with {task, input_data}.

    agent_name : name of the agent (for logging and identification)
    task       : description of the task to execute
    input_data : JSON string with structured data for the sub-agent
    endpoint   : base URL of the sub-agent (e.g. "http://localhost:8001")
    """
    if not endpoint:
        return (
            f"ERROR: endpoint is required for call_agent '{agent_name}'. "
            f"Example: endpoint='http://localhost:8001'"
        )

    try:
        import requests
        resp = requests.post(
            f"{endpoint}/run",
            json={"task": task, "input": input_data},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return f"ERROR: call to agent '{agent_name}' ({endpoint}) failed — {e}"


def todo_execute(todo_path: str = "todo.json",
                 dry_run: bool = False) -> str:
    """
    [G] Iterate the task list and dispatch each task to the correct skill or agent.
    Handles status tracking and failures for each task.

    todo_path : JSON file produced by todo_create
    dry_run   : if True, show the plan without executing
    """
    from skills.d import read_file
    from skills import ALL_SKILLS

    raw = read_file(todo_path)
    if raw.startswith("ERROR"):
        return raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid JSON in {todo_path}: {e}"

    # Supports both a plain list and the format produced by todo_create
    # {"tasks": [...], "created_at": "..."}
    if isinstance(parsed, list):
        tasks = parsed
    elif isinstance(parsed, dict) and "tasks" in parsed:
        tasks = parsed["tasks"]
    else:
        return "ERROR: the todo file does not contain a recognizable task list"

    lines: list[str] = []
    done = failed = skipped = 0

    for i, task in enumerate(tasks):
        desc     = task.get("description", f"task_{i}")
        assignee = task.get("assignee", "")
        priority = task.get("priority", "medium")

        if dry_run:
            lines.append(
                f"[DRY] {i+1}. {desc}\n"
                f"      assignee={assignee or '(none)'}  priority={priority}"
            )
            continue

        lines.append(f"\n[{i+1}] {desc}  (assignee={assignee or '(none)'}, priority={priority})")

        if not assignee:
            lines.append("  SKIP: no assignee defined")
            skipped += 1
            task["status"] = "skipped"
            continue

        if assignee not in ALL_SKILLS:
            lines.append(f"  SKIP: skill '{assignee}' not found")
            skipped += 1
            task["status"] = "skipped"
            continue

        fn = ALL_SKILLS[assignee]
        try:
            result = str(fn(desc))
            if result.startswith("ERROR"):
                lines.append(f"  FAIL: {result[:200]}")
                task["status"] = "failed"
                failed += 1
            else:
                lines.append(f"  OK: {result[:200]}")
                task["status"] = "done"
                done += 1
        except NotImplementedError:
            lines.append(f"  SKIP: skill '{assignee}' not yet implemented")
            skipped += 1
            task["status"] = "skipped"
        except Exception as e:
            lines.append(f"  FAIL: {e}")
            task["status"] = "failed"
            failed += 1

    if dry_run:
        return f"DRY RUN — {len(tasks)} tasks:\n" + "\n".join(lines)

    summary = (
        f"\nExecution complete: {done} done, {failed} failed, "
        f"{skipped} skipped out of {len(tasks)} total tasks"
    )
    return "\n".join(lines) + summary


# ─────────────────────────────────────────────────────────────
# QUALITY
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────

SKILLS: dict[str, Callable] = {
    "llm_invoke":       llm_invoke,
    "vision_interpret": vision_interpret,
    "web_search":       web_search,
    "context_compress": context_compress,
    "call_agent":       call_agent,
    "todo_execute":     todo_execute,
    "critic_validate":  critic_validate,
}
