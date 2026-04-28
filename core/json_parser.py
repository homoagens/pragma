# json_parser.py — robust extraction of the first JSON object from free text.
#
# Why this is needed: models in "thinking mode" often produce narrative text
# before and/or after the JSON, or multiple consecutive JSON objects. A simple
# `json.loads(text)` fails; `text[text.index("{"):text.rindex("}")+1]`
# fails when a second JSON follows the first.
#
# Solution: scan the text counting braces { and }, ignoring those inside
# strings. Returns the FIRST balanced JSON object found.

import json


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
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"Response not parseable as JSON: {e}\n{text[:300]}"
                    )

    raise RuntimeError(f"No balanced JSON found:\n{text[:300]}")
