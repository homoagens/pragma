# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# skills/_template/skill.py — Template for new skills
#
# CATEGORY:
#   D (Deterministic) — no LLM call, reproducible output
#   H (Hybrid)        — deterministic execution + LLM judgment
#   G (Delegable)     — delegated to an external entity (LLM, agent, API)
#
# CONVENTIONS:
#   - The main function has the SAME NAME as the folder
#   - Always returns str (even on error)
#   - Errors:    "ERROR: <human-readable message>"
#   - Successes: "OK: ..." or the requested content
#   - Internal helpers: prefixed with _ (e.g. _parse_input)
#   - Late imports for cross-skill dependencies (see below)

from __future__ import annotations

# Standard imports — fine at top level, always available
import json  # noqa: F401
from pathlib import Path  # noqa: F401

# Core imports — fine at top level (core/ is on sys.path)
# import llm_client          # for H and G skills
# import config              # for configurable parameters
# from json_parser import extract_json   # to parse LLM output

# Cross-skill imports — ALWAYS late (inside the function) to avoid
# circular dependencies during loading. Example:
#   def my_skill(path: str) -> str:
#       from skills.read_file.skill import read_file   # <- late import
#       content = read_file(path)
#       ...

# Shared utilities
from skills._utils import _now   # noqa: F401  # UTC timestamp


# ── Internal helpers ──────────────────────────────────────────

def _validate_input(value: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not value or not value.strip():
        return False, "input must not be empty"
    return True, ""


# ── Main skill ────────────────────────────────────────────────

def my_skill(text: str, mode: str = "upper", prefix: str = "") -> str:
    """
    [D] Example skill: transform text.
    Replace this docstring with one concise sentence.

    text   : input text to transform
    mode   : "upper" | "lower" | "title"
    prefix : optional string prepended to the result
    Returns: transformed text or "ERROR: ..."
    """
    # 1. Validate input
    ok, err = _validate_input(text)
    if not ok:
        return f"ERROR: {err}"

    valid_modes = ("upper", "lower", "title")
    if mode not in valid_modes:
        return f"ERROR: invalid mode '{mode}'. Valid: {valid_modes}"

    # 2. Execute
    try:
        if mode == "upper":
            result = text.upper()
        elif mode == "lower":
            result = text.lower()
        else:
            result = text.title()

        if prefix:
            result = f"{prefix}{result}"

        return result

    except Exception as e:
        return f"ERROR: {e}"
