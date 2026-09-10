# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from typing import Any

import llm_client


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
