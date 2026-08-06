# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# memory.py — context compression for agents with long conversations.
# Transparent to the agent: takes the message list, returns an optionally
# compressed version (same structure, fewer elements).

import config
import llm_client

SYSTEM_PROMPT_SUMMARY = """You are an assistant specialized in summarizing conversations.
You receive a sequence of messages and produce a compact but faithful summary.
Preserve all important factual information.
Respond ONLY with the summary text — no JSON, no prefixes."""


def summarize(text, context="conversation", model=None):
    """Single LLM call to compress text. No loop."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_SUMMARY},
        {"role": "user",
         "content": f"Summarize this {context}, preserving all important facts:\n\n{text}"},
    ]
    return llm_client.call_llm(
        messages    = messages,
        model       = model,
        # Not 0.0 like the memory faculties and not the session's either: see
        # config.SUMMARY_TEMPERATURE for why this call is its own case.
        temperature = config.SUMMARY_TEMPERATURE,
        max_tokens  = 2048,
    )


def compress(messages, threshold=None, context="conversation", model=None,
             protect=None):
    """
    If the message list exceeds the threshold, compress old messages into a summary.
    With threshold=0 forces compression regardless of count
    (useful for character-based threshold — see react.py).

    Always preserves:
      - the system prompt at position 0 (if present)
      - the last config.MESSAGES_RECENT messages

    `protect` extends the preserved head beyond the system prompt: the first
    `protect` messages are left exactly as they are. It exists for the live
    session, where the head is not a prompt but the CONVERSATION — earlier
    turns that a summary must never be allowed to blur. There, overflow is
    handled by consolidating those turns into episodes (agent/chat.py), and
    this function's job shrinks to the current turn's own tool traffic.
    Default None keeps the historical behaviour exactly: system prompt only.

    Returns the compressed list, or unchanged if below threshold.
    """
    if threshold is None:
        threshold = config.MAX_MESSAGES
    if len(messages) <= threshold:
        return messages

    has_system = bool(messages) and messages[0].get("role") == "system"

    head_n = (1 if has_system else 0) if protect is None else max(protect, 0)
    head_n = min(head_n, len(messages))
    head   = messages[:head_n]

    # The recent window is carved out of what is LEFT after the head, never out
    # of the whole list. With a long protect fence the two would otherwise
    # overlap and the same messages would be emitted twice - head and window
    # both claiming them. Harmless while nothing was compressed, a duplicated
    # conversation the moment something is.
    tail        = messages[head_n:]
    recent_n    = min(config.MESSAGES_RECENT, len(tail))
    to_compress = tail[:len(tail) - recent_n]
    recent      = tail[len(tail) - recent_n:]

    # MESSAGES_RECENT is a COUNT, and a count is not a size. Six messages can be
    # three hundred tokens or thirty thousand, and the six are preserved either
    # way - so a window that will not fit could not be made to fit by
    # compressing, no matter how hard: the part that overflowed was the part
    # nobody was allowed to touch.
    #
    # The excess is MOVED into the summarised half rather than dropped: it is
    # still recent, it just stops being verbatim, and nothing is lost that the
    # summary cannot carry.
    #
    # The subtlety is the tool protocol. A `tool` message is the RESULT of the
    # assistant turn before it, and a result whose call has been summarised away
    # is an orphan that most servers reject outright. So after trimming, any
    # leading `tool` messages follow their call into the summary.
    budget = getattr(config, "RECENT_MAX_CHARS", 0)
    if budget > 0 and recent:
        def _size(ms):
            return sum(len(m.get("content") or "") for m in ms)
        while len(recent) > 1 and _size(recent) > budget:
            to_compress.append(recent.pop(0))
        while len(recent) > 1 and (recent[0].get("role") == "tool"):
            to_compress.append(recent.pop(0))

    if not to_compress:
        return messages

    # Per-message truncation: 500 chars was too aggressive (file reads got
    # gutted before they reached the summarizer). The cap is now configurable
    # via MESSAGE_COMPRESS_TRUNC. A "[+ N more chars]" marker is appended
    # when content is clipped so the summarizer knows information was lost.
    trunc = getattr(config, "MESSAGE_COMPRESS_TRUNC", 2000)
    parts = []
    for m in to_compress:
        body = m.get("content", "") or ""
        # Under the native tool protocol the action lives in `tool_calls` and
        # `content` is empty. Rendering it keeps the actions visible to the
        # summarizer: otherwise a compressed history would remember the
        # observations while forgetting what produced them.
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            call = f"{fn.get('name', '?')}({fn.get('arguments', '')})"
            body = (body + "\n" if body else "") + f"[ACTION] {call}"
        if len(body) > trunc:
            body = body[:trunc] + f" [+ {len(body) - trunc} more chars]"
        parts.append(f"{m['role'].upper()}: {body}")
    text = "\n".join(parts)

    if config.DEBUG:
        print(f"[memory] Compressing {len(to_compress)} messages ({context})...")
    summary = summarize(text, context, model=model)

    summary_msg = {
        "role":    "user",
        "content": f"[SUMMARY OF WHAT HAPPENED SO FAR]:\n{summary}",
    }

    return list(head) + [summary_msg] + recent
