# skills/h.py — Hybrid skills [H]
#
# The mechanical execution is deterministic, but the decision of WHAT to execute
# (which patch to apply, what is worth saving, how to phrase the question)
# requires LLM judgment. The LLM call is isolated here — it does not leak into d.py.
#
# Skills covered (5):
#   edit_file, memory_store, memory_retrieve, parse_document, ask_user

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import llm_client
import config
from json_parser import extract_json
from skills.d import read_file, write_file


# ─────────────────────────────────────────────────────────────
# FILESYSTEM
# ─────────────────────────────────────────────────────────────

_EDIT_SYSTEM = """You are a precise file editor.
Given a file content and an instruction, produce a JSON object with these keys:
  "old_text" : the exact substring to replace (must exist verbatim in the file)
  "new_text" : the replacement text
  "reason"   : one sentence explaining what you did (or why you made no change)

Rules:
- old_text must be copied character-for-character from the file, including whitespace and indentation
- If the instruction refers to something that does not exist in the file, return old_text="" and new_text="" with a reason explaining what was not found
- If the instruction requires adding content at the end of the file, old_text can be the last line
- Respond with ONLY the JSON object, no explanation"""


def edit_file(path: str, instruction: str) -> str:
    """
    [H] Surgical patch to a file.
    Deterministic mechanism: reads the file, applies exact str.replace().
    LLM judgment: interprets the instruction and produces old_text + new_text.

    path        : file to modify
    instruction : natural language description of the change
    Returns     : "OK: ..." with patch summary, or "ERROR: ..."
    """
    # 1. Read the file [D]
    content = read_file(path)
    if content.startswith("ERROR"):
        return content

    # 2. Ask the LLM for the patch [H]
    user_msg = f"File content:\n```\n{content}\n```\n\nInstruction: {instruction}"
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _EDIT_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        patch = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    old_text = patch.get("old_text", "")
    new_text = patch.get("new_text", "")

    if not old_text:
        reason = patch.get("reason", "no change needed")
        return f"SKIP: {reason}"

    # 3. Verify that old_text exists in the file [D]
    if old_text not in content:
        return (
            f"ERROR: old_text not found in file.\n"
            f"LLM produced: {old_text!r}\n"
            f"Hint: the LLM may have altered whitespace or indentation."
        )

    # 4. Apply the replacement [D]
    new_content = content.replace(old_text, new_text, 1)

    # 5. Write the file [D]
    result = write_file(path, new_content)
    if result.startswith("ERROR"):
        return result

    return (
        f"OK: patch applied to {path}\n"
        f"  old: {old_text!r}\n"
        f"  new: {new_text!r}"
    )


# ─────────────────────────────────────────────────────────────
# MEMORY & STATE
# ─────────────────────────────────────────────────────────────

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
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _MEMORY_RETRIEVE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
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


# ─────────────────────────────────────────────────────────────
# INFORMATION RETRIEVAL
# ─────────────────────────────────────────────────────────────

_PARSE_SYSTEM = """You are a document content extractor.
Given cleaned document text and an extraction target, extract the requested content.

Respond with ONLY a JSON object:
{
  "result": "the extracted content as a clean string",
  "reason": "one sentence on what you extracted"
}

Extraction targets:
- main_text    : primary readable content only, no navigation/header/footer/ads
- links        : all URLs found, one per line as "anchor text: url"
- summary      : concise 2-3 sentence summary of the document
- code_blocks  : all code snippets preserving formatting, separated by ---
- (empty)      : extract all meaningful structured content, preserving sections"""

_HTML_ENTITIES = [
    ("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
    ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
    ("&apos;", "'"),
]


def _clean_html(html: str) -> str:
    """
    Deterministic HTML cleanup.
    Operation order:
      1. remove script/style (including content)
      2. convert <a href> to "text [url]" — preserves URLs for the LLM
      3. mark <pre>/<code> blocks with newlines — preserves code structure
      4. remove all remaining tags
      5. decode HTML entities
      6. normalize whitespace
    """
    import re

    # 1. Remove script and style (including content)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)

    # 2. Convert anchor tags to "text [url]" before stripping
    def _anchor(m):
        inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        url   = m.group(1).strip()
        return f"{inner} [{url}]" if inner else f"[{url}]"

    html = re.sub(
        r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        _anchor,
        html, flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Convert pre/code to readable blocks (newlines in place of tags)
    html = re.sub(r"<pre[^>]*>",  "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"</pre>",       "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"<code[^>]*>",  "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"</code>",      "\n",  html, flags=re.IGNORECASE)

    # 4. Remove all remaining HTML tags
    html = re.sub(r"<[^>]+>", " ", html)

    # 5. Decode common entities
    for entity, char in _HTML_ENTITIES:
        html = html.replace(entity, char)

    # 6. Normalize whitespace
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _detect_type(content: str) -> str:
    """Auto-detect document type from the first 500 chars."""
    import re
    sample = content[:500]
    if re.search(r"<[a-z]+[\s>]", sample, re.IGNORECASE):
        return "html"
    if re.search(r"^#{1,6}\s", sample, re.MULTILINE):
        return "markdown"
    return "plain"


def parse_document(content: str, doc_type: str = "auto",
                   extract: str = "", max_input_chars: int = 20_000) -> str:
    """
    [H] Extract structure from HTML or raw text.
    Deterministic mechanism: strip HTML, normalize whitespace.
    LLM judgment: extracts the requested content from the cleaned text.

    content        : raw content (e.g. output of web_fetch)
    doc_type       : "html" | "markdown" | "plain" | "auto"
    extract        : "main_text" | "links" | "summary" | "code_blocks" | ""
    max_input_chars: truncates input to the model to avoid exceeding context
    Returns        : extracted text or "ERROR: ..."
    """
    if not content or not content.strip():
        return "ERROR: empty content"

    # 1. Auto-detect and pre-clean [D]
    detected = _detect_type(content) if doc_type == "auto" else doc_type
    cleaned  = _clean_html(content) if detected == "html" else content.strip()

    # Truncate if too long for the context window
    if len(cleaned) > max_input_chars:
        cleaned = cleaned[:max_input_chars] + "\n... [truncated]"

    # 2. Ask the LLM to extract the content [H]
    target_desc = extract if extract else "all meaningful content"
    user_msg = (
        f"Document type: {detected}\n"
        f"Extract: {target_desc}\n\n"
        f"Document text:\n{cleaned}"
    )

    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
        )
        result = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    # 3. Return the result [D]
    return result.get("result", "ERROR: LLM returned no result")


# ─────────────────────────────────────────────────────────────
# HUMAN INTERACTION
# ─────────────────────────────────────────────────────────────

_ASK_SYSTEM = """You are a communication assistant for an AI agent.
Given a topic and optional context, formulate the clearest possible question to ask a human user.

Respond with ONLY a JSON object:
{
  "question": "the formulated question, clear and specific",
  "hint":     "optional brief hint on expected format or valid values (empty string if none)"
}

Keep the question concise, direct, and unambiguous.
For confirm mode, phrase it as a yes/no question.
For choice mode, list the options clearly inside the question."""


def ask_user(topic: str, context: str = "", mode: str = "input") -> str:
    """
    [H] Pause execution and request input or approval from the user.
    Deterministic mechanism: input() from console.
    LLM judgment: formulates the question clearly and in context.

    topic   : subject to ask about
    context : additional context for formulating the question
    mode    : "input" (free text) | "confirm" (y/n) | "choice" (option list)
    Returns : user answer as a string; "yes"/"no" for confirm mode
    """
    # 1. Build the message for the LLM [H]
    user_msg = f"Topic: {topic}"
    if context:
        user_msg += f"\nContext: {context}"
    if mode == "confirm":
        user_msg += "\nMode: yes/no — phrase as a question the user can answer with y or n"
    elif mode == "choice":
        user_msg += "\nMode: choice — list available options clearly inside the question"

    # 2. LLM formulates the optimal question [H]
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _ASK_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
        )
        formulated = extract_json(raw)
    except Exception:
        # Fallback: use topic directly without LLM formulation
        formulated = {"question": topic, "hint": ""}

    question = formulated.get("question", topic)
    hint     = formulated.get("hint", "")

    # 3. Show the question and collect the answer [D]
    header = f"\n[INPUT REQUEST]\n{question}"
    if hint:
        header += f"\n({hint})"

    if mode == "confirm":
        answer = input(f"{header} [y/n]: ").strip().lower()
        return "yes" if answer in ("y", "yes", "1") else "no"
    else:
        return input(f"{header}\n> ").strip()


# ─────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────

SKILLS: dict[str, Callable] = {
    "edit_file":        edit_file,
    "memory_store":     memory_store,
    "memory_retrieve":  memory_retrieve,
    "parse_document":   parse_document,
    "ask_user":         ask_user,
}
