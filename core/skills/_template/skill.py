# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# skills/_template/skill.py — Template per nuove skill
#
# CATEGORIA:
#   D (Deterministic) — nessuna chiamata LLM, output riproducibile
#   H (Hybrid)        — esecuzione deterministica + LLM judgment
#   G (Delegable)     — delega a entità esterna (LLM, agente, API)
#
# CONVENZIONI:
#   - La funzione principale ha lo STESSO NOME della cartella
#   - Ritorna sempre str (anche in caso di errore)
#   - Errori: "ERROR: <messaggio leggibile>"
#   - Successi: "OK: ..." oppure il contenuto richiesto
#   - Helper interni: prefisso _ (es. _parse_input)
#   - Late import per dipendenze cross-skill (vedi sotto)

from __future__ import annotations

# Import standard — ok a top-level perché sempre disponibili
import json  # noqa: F401
from pathlib import Path  # noqa: F401

# Import dal core — ok a top-level (core/ è in sys.path)
# import llm_client          # per skill H e G
# import config              # per parametri configurabili
# from json_parser import extract_json   # per parsare output LLM

# Import cross-skill — SEMPRE late import (dentro la funzione)
# per evitare dipendenze circolari durante il caricamento.
# Esempio:
#   def my_skill(path: str) -> str:
#       from skills.read_file.skill import read_file   # ← late import
#       content = read_file(path)
#       ...

# Utility condivise
from skills._utils import _now   # noqa: F401  # timestamp UTC


# ── Helper interni ────────────────────────────────────────────

def _validate_input(value: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not value or not value.strip():
        return False, "input must not be empty"
    return True, ""


# ── Skill principale ──────────────────────────────────────────

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
