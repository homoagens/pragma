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


def _parse_or_repair(candidate: str):
    """Try strict json.loads, fall back to json_repair on failure.
    Raises json.JSONDecodeError if both fail (so callers can re-raise as
    RuntimeError with context). Repaired output is logged at debug level
    so we know when it happens."""
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
        return repaired


def extract_json(text):
    """
    Extracts the first complete JSON object from a model response.
    Raises RuntimeError if none is found.
    """
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
