from __future__ import annotations

import config
import llm_client
from json_parser import extract_json


_EDIT_SYSTEM = """You are a precise file editor.
Given a file content and an instruction, produce a JSON object with these keys:
  "old_text" : the exact substring to replace (must exist verbatim in the file)
  "new_text" : the replacement text
  "reason"   : one sentence explaining what you did (or why you made no change)

Rules:
- old_text must be copied character-for-character from the file, including whitespace and indentation
- Keep old_text MINIMAL — the shortest unique substring that anchors the change.
  Do NOT copy huge surrounding context; copy only what is being replaced.
- If the instruction refers to something that does not exist in the file, return old_text="" and new_text="" with a reason explaining what was not found
- If the instruction requires adding content at the end of the file, old_text can be the last line
- Respond with ONLY the JSON object, no explanation, no prose, no markdown fences"""


def _ask_llm_for_patch(content: str, instruction: str, terse: bool = False) -> dict:
    """Single LLM call → patch dict. Raises on failure."""
    extra = (
        "\n\nIMPORTANT: be ultra concise. Output ONLY the JSON. "
        "old_text must be a SHORT unique anchor (one or two lines)."
        if terse else ""
    )
    user_msg = (
        f"File content:\n```\n{content}\n```\n\n"
        f"Instruction: {instruction}{extra}"
    )
    raw = llm_client.call_llm(
        messages=[
            {"role": "system", "content": _EDIT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=config.SKILL_MAX_TOKENS,
    )
    return extract_json(raw)


def edit_file(path: str, instruction: str) -> str:
    """
    [H] Surgical patch to a file.
    Deterministic mechanism: reads the file, applies exact str.replace().
    LLM judgment: interprets the instruction and produces old_text + new_text.

    path        : file to modify
    instruction : natural language description of the change
    Returns     : "OK: ..." with patch summary, or "ERROR: ..."
    """
    from skills.read_file.skill import read_file
    from skills.write_file.skill import write_file

    # 1. Read the file [D]
    content = read_file(path)
    if content.startswith("ERROR"):
        return content

    # 2. Ask the LLM for the patch [H] — with one retry on truncation
    try:
        try:
            patch = _ask_llm_for_patch(content, instruction, terse=False)
        except RuntimeError as e:
            # finish_reason=length → retry once asking for ultra-concise output
            if "truncated" in str(e).lower():
                patch = _ask_llm_for_patch(content, instruction, terse=True)
            else:
                raise
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
            f"Hint: the LLM may have altered whitespace or indentation. "
            f"Try replace_in_file with an exact short string instead."
        )

    # 4. Apply the replacement [D]
    new_content = content.replace(old_text, new_text, 1)

    # 5. Write the file [D]
    # edit_file always modifies an existing file by design — opt in to overwrite.
    result = write_file(path, new_content, overwrite=True)
    if result.startswith("ERROR"):
        return result

    return (
        f"OK: patch applied to {path}\n"
        f"  old: {old_text!r}\n"
        f"  new: {new_text!r}"
    )
