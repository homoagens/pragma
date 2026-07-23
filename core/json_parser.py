# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# json_parser.py — robust extraction of the first JSON object from free text.
#
# Why this is needed: models in "thinking mode" often produce narrative text
# before and/or after the JSON, or multiple consecutive JSON objects. A simple
# `json.loads(text)` fails; `text[text.index("{"):text.rindex("}")+1]`
# fails when a second JSON follows the first.
#
# Solution: scan the text counting braces { and }, ignoring those inside
# strings. Returns the FIRST balanced JSON object found.
#
# Fallback: if strict json.loads fails on the extracted substring (the model
# emitted literal control chars, unescaped quotes inside the string value,
# truncated \uXXXX escapes, trailing commas, etc.), retry through json_repair
# which is specifically designed for malformed LLM JSON output.

import json

try:
    from json_repair import repair_json as _repair_json  # type: ignore
    _HAS_REPAIR = True
except Exception:  # pragma: no cover — optional dependency
    _HAS_REPAIR = False


import re as _re

# Keys we tag onto recovered dicts to signal that JSON repair fired and may
# have dropped fields. react.py reads these and surfaces a hint to the model.
REPAIR_FLAG_KEY    = "__pragma_json_repaired__"
REPAIR_LOST_KEY    = "__pragma_json_lost_keys__"

# Heuristic list of arg-like keys that commonly appear in agent action
# payloads. We only flag a "lost" key when one of THESE appears as a JSON
# key in the raw text but is missing from the recovered dict (top-level OR
# under args). Avoids false positives on prose that happens to contain
# words like "path:" in user content.
_KNOWN_KEYS = (
    "path", "action", "args", "content", "old", "new", "anchor",
    "instruction", "old_b64", "new_b64", "pattern", "command", "cwd",
    "topic", "question",
)
_KEY_PATTERN = _re.compile(
    r'"\s*(' + "|".join(_KNOWN_KEYS) + r')\s*"\s*:', _re.IGNORECASE,
)


def _detect_lost_keys(raw: str, recovered) -> list[str]:
    """Compare the keys that look JSON-encoded in `raw` against the keys
    present in `recovered` (top-level and under `args`). Returns the names
    that were in the raw text but did NOT make it into the parsed dict.
    Heuristic — only the known agent keys above are checked."""
    if not isinstance(recovered, dict):
        return []
    raw_keys = {m.group(1).lower() for m in _KEY_PATTERN.finditer(raw or "")}
    if not raw_keys:
        return []
    present = {k.lower() for k in recovered.keys()}
    args_obj = recovered.get("args")
    if isinstance(args_obj, dict):
        present.update(k.lower() for k in args_obj.keys())
    lost = sorted(raw_keys - present)
    # Drop internal repair flag names from the result (they're never lost
    # in a meaningful sense even though they could match the pattern).
    return [k for k in lost if not k.startswith("__pragma")]


def _parse_or_repair(candidate: str):
    """Try strict json.loads, fall back to json_repair on failure.
    Raises json.JSONDecodeError if both fail (so callers can re-raise as
    RuntimeError with context). When repair fires, the returned dict is
    tagged with REPAIR_FLAG_KEY=True and (when applicable) REPAIR_LOST_KEY
    listing the agent-known keys that appear in the raw text but didn't
    survive parsing — the agent loop uses these to warn the model."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as strict_err:
        if not _HAS_REPAIR:
            raise
        try:
            # json_repair returns a JSON STRING by default; passing
            # return_objects=True gives us the parsed object directly.
            repaired = _repair_json(candidate, return_objects=True)
        except Exception:
            # Even the lenient parser gave up — surface the original error.
            raise strict_err
        # json_repair returns an empty string when truly hopeless.
        if repaired == "" or repaired is None:
            raise strict_err
        # Annotate the recovered dict so the agent layer can surface a hint
        # to the model. Non-dict recoveries (lists, scalars) are returned
        # as-is — annotation only fits on dicts.
        if isinstance(repaired, dict):
            repaired[REPAIR_FLAG_KEY] = True
            lost = _detect_lost_keys(candidate, repaired)
            if lost:
                repaired[REPAIR_LOST_KEY] = lost
        return repaired


def extract_json(text):
    """
    Extracts the first complete JSON object from a model response.
    Raises RuntimeError if none is found.
    """
    # When a response is cut by finish_reason=length, llm_client returns the
    # partial text prefixed with a truncation marker. react.py strips it
    # itself, but skills that call call_llm directly (edit_file,
    # episode_consolidate, ...) pass the raw text here —
    # strip it centrally so every consumer can still salvage the partial.
    # Kept as a literal to avoid importing llm_client from this
    # dependency-free module; must match llm_client.TRUNCATION_PARTIAL_MARKER.
    _trunc = "__PRAGMA_TRUNCATED_PARTIAL__"
    if text.startswith(_trunc):
        text = text[len(_trunc):]

    try:
        start = text.index("{")
    except ValueError:
        raise RuntimeError(f"No JSON found in response:\n{text[:300]}")

    depth     = 0
    in_string = False
    escaped   = False
    for i, c in enumerate(text[start:], start):
        if escaped:
            escaped = False
            continue
        if c == "\\" and in_string:
            escaped = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i+1]
                try:
                    return _parse_or_repair(candidate)
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"Response not parseable as JSON (even after repair): {e}\n"
                        f"{text[:300]}"
                    )

    # Unbalanced output — common when the LLM was truncated. Try repair on
    # the partial substring too: json_repair often closes missing braces.
    if _HAS_REPAIR:
        try:
            return _parse_or_repair(text[start:])
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"No balanced JSON found:\n{text[:300]}")
