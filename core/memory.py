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
        temperature = 0.2,
        max_tokens  = 2048,
    )


def compress(messages, threshold=None, context="conversation", model=None):
    """
    If the message list exceeds the threshold, compress old messages into a summary.
    With threshold=0 forces compression regardless of count
    (useful for character-based threshold — see agent.py).

    Always preserves:
      - the system prompt at position 0 (if present)
      - the last config.MESSAGES_RECENT messages

    Returns the compressed list, or unchanged if below threshold.
    """
    if threshold is None:
        threshold = config.MAX_MESSAGES
    if len(messages) <= threshold:
        return messages

    recent_n   = config.MESSAGES_RECENT
    has_system = bool(messages) and messages[0].get("role") == "system"

    if has_system:
        system_msg    = messages[0]
        to_compress   = messages[1:-recent_n]
        recent        = messages[-recent_n:]
    else:
        system_msg    = None
        to_compress   = messages[:-recent_n]
        recent        = messages[-recent_n:]

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

    if has_system:
        return [system_msg, summary_msg] + recent
    return [summary_msg] + recent
