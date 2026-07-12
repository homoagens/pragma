# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import json


def schema_validate(data: str, required_fields: str = "",
                    field_types: str = "") -> str:
    """
    Verify that data is valid JSON and matches the expected structure.
    required_fields : mandatory fields separated by comma (e.g. "id,name,status")
    field_types     : JSON string {"field": "str|int|float|bool|list|dict"}
                      e.g. '{"id":"int","name":"str"}'
    Returns "VALID" or "INVALID: <reason>".
    """
    _type_map = {"str": str, "int": int, "float": float,
                 "bool": bool, "list": list, "dict": dict}

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return f"INVALID: not valid JSON — {e}"

    errors: list[str] = []

    if required_fields:
        for field in [f.strip() for f in required_fields.split(",") if f.strip()]:
            if field not in parsed:
                errors.append(f"missing required field: '{field}'")

    if field_types:
        try:
            types = json.loads(field_types)
            for field, expected in types.items():
                cls = _type_map.get(expected)
                if cls and field in parsed:
                    if not isinstance(parsed[field], cls):
                        actual = type(parsed[field]).__name__
                        errors.append(f"field '{field}': expected {expected}, got {actual}")
        except json.JSONDecodeError as e:
            errors.append(f"invalid field_types JSON: {e}")

    if errors:
        return "INVALID:\n" + "\n".join(f"  - {e}" for e in errors)
    return "VALID"
