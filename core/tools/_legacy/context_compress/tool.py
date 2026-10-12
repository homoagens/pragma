# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from typing import Any



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
