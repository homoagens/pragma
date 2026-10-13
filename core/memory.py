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
    """Single LLM call to compress text. No loop.

    A faculty like the others: named, so it is shown and routed as one, and
    told in so many words not to reason - config.summary_call says why.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_SUMMARY},
        {"role": "user",
         "content": f"Summarize this {context}, preserving all important facts:\n\n{text}"},
    ]
    how = config.summary_call()
    with llm_client.faculty("SUMMARIZER"):
        out = llm_client.call_llm(
            messages        = messages,
            model           = model,
            temperature     = how["temperature"],
            max_tokens      = 2048,
            template_kwargs = how["template_kwargs"],
            sampling        = how["sampling"],
        )
    # A summary cut at its budget is still worth having, but the marker that
    # says so belongs to llm_client, not to the model: it used to reach the
    # agent's context verbatim, as the first word of the summary. Said in words.
    marker = llm_client.TRUNCATION_PARTIAL_MARKER
    if out.startswith(marker):
        out = out[len(marker):].rstrip() + " [... the summary was cut short here]"
    return out


# HOW MUCH OF A MESSAGE THE SUMMARIZER READS. It used to be a fixed number of
# characters, 2000 a message, chosen when the largest thing in a history was a
# file that had been read. A tool on another server returns what it returns -
# fifty thousand characters of search results is an ordinary answer - and a
# fixed cut gave the summarizer the first twenty-fifth of it and asked for a
# faithful summary of the whole.
#
# So nothing is cut while everything fits. What "fits" means is the window of
# the model doing the summarizing, less the summary it has to write. When the
# text is larger than that, the LONGEST messages give way first, each down to
# the same level, and each keeps its opening and its end: the short ones, which
# are the requests and the decisions, are never touched to make room for one
# long listing.
#
# The level is worked out in characters and the window is in tokens, so a ratio
# stands between them. The caller passes the one the server last measured on
# this very conversation when it has it; 3 otherwise, which is honest for prose
# and optimistic for JSON - which is why a refused prompt halves it and tries
# again.
_RATIO = 3.0


def _render(m: dict) -> tuple[str, str]:
    """(role, text) of one message, with the calls it made written out.

    Under the native tool protocol the action lives in `tool_calls` and
    `content` is empty. Rendering it keeps the actions visible to the
    summarizer: otherwise a compressed history would remember the observations
    while forgetting what produced them.
    """
    body = m.get("content", "") or ""
    for tc in (m.get("tool_calls") or []):
        fn = tc.get("function") or {}
        call = f"{fn.get('name', '?')}({fn.get('arguments', '')})"
        body = (body + "\n" if body else "") + f"[ACTION] {call}"
    return str(m.get("role", "?")).upper(), body


def _level(sizes: list[int], budget: int) -> int:
    """The length every message is held to so that they sum to `budget`.

    Messages shorter than the level keep all of themselves; what they do not
    use is shared among the longer ones. Returns a number larger than any
    message when everything fits.
    """
    if sum(sizes) <= budget:
        return max(sizes, default=0) + 1
    left, level = budget, 0
    for i, size in enumerate(sorted(sizes)):
        share = left // (len(sizes) - i)
        if size <= share:
            left -= size
            continue
        level = share
        break
    return max(level, 200)


def _text_for(messages, budget_chars: int, fixed: int = 0) -> str:
    """The messages as one text a summarizer can read, inside `budget_chars`."""
    rendered = [_render(m) for m in messages]
    level = fixed if fixed > 0 else _level([len(b) for _r, b in rendered], budget_chars)
    parts = []
    for role, body in rendered:
        if len(body) > level:
            # The opening and the end: a result's last lines are as often what
            # mattered as its first, and the marker says how much went.
            head = body[: level * 2 // 3]
            tail = body[len(body) - level // 3:] if fixed <= 0 else ""
            gone = len(body) - len(head) - len(tail)
            body = (f"{head} [+ {gone} more chars]" if not tail
                    else f"{head}\n[... {gone} characters left out here ...]\n{tail}")
        parts.append(f"{role}: {body}")
    return "\n".join(parts)


def _budget_chars(reply_tokens: int, ratio: float | None) -> int:
    """Characters of conversation one summarizing call can be handed."""
    window = int(getattr(config, "CONTEXT_WINDOW", 0) or 0) or 32768
    room = max(1024, window - reply_tokens - 1024)
    return int(room * min(max(ratio or _RATIO, 1.0), 6.0))


# What stands in for a summary the summarizer could not write: the opening of
# each earlier message, the newest kept when they do not all fit.
_CUT_LINE  = 240
_CUT_TOTAL = 12000


def _cut(msgs, why) -> str:
    """A summary written without a model: the opening of every message.

    THE RUN GOES ON. The agent loop compresses outside the try that guards the
    model's own calls, so a summarizer that failed - a timeout, a refused
    prompt, a reasoning cut short - used to end the run with a traceback and
    take every step before it along. Losing the detail of old steps is what
    compressing does anyway; losing the run is not.
    """
    lines = []
    for m in msgs:
        body = " ".join((m.get("content") or "").split())
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            call = f"[ACTION] {fn.get('name', '?')}({fn.get('arguments', '')})"
            body = f"{body} {call}" if body else call
        if len(body) > _CUT_LINE:
            body = body[:_CUT_LINE] + "..."
        lines.append(f"{m.get('role', '?').upper()}: {body}")
    kept, size = [], 0
    for line in reversed(lines):
        if kept and size + len(line) > _CUT_TOTAL:
            break
        kept.append(line)
        size += len(line) + 1
    kept.reverse()
    head = (f"(The summarizer failed - {str(why)[:120]} - so this is the opening "
            f"of each earlier message instead.)")
    if len(kept) < len(lines):
        head += f"\n({len(lines) - len(kept)} older messages left out.)"
    return head + "\n" + "\n".join(kept)


def compress(messages, threshold=None, context="conversation", model=None,
             protect=None, recent=None, ratio=None):
    """
    If the message list exceeds the threshold, compress old messages into a summary.
    With threshold=0 forces compression regardless of count - which is how the
    agent loop calls it, having decided by size (see react.py). threshold=None
    means config.MAX_MESSAGES, and does nothing when that is 0, the default.

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

    `recent` overrides config.MESSAGES_RECENT. 0 keeps nothing verbatim: the
    last resort, for a prompt the server has refused twice, where the message
    that does not fit may be the very last one.

    `ratio` is characters per token as the server last measured them on this
    conversation, when the caller knows; see _RATIO.

    Returns the compressed list, or unchanged if below threshold.
    """
    if threshold is None:
        threshold = config.MAX_MESSAGES
        if threshold <= 0:
            return messages
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
    recent_n    = min(config.MESSAGES_RECENT if recent is None else max(recent, 0),
                      len(tail))
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
        # And the other way round: a result is not left without its call. The
        # two loops above stop at one message, and when that message is a tool
        # result its call has just gone into the summary - the orphan again,
        # by the back door. The call comes back, budget or no budget: a prompt
        # that is then too large is refused and handled as one, which a
        # malformed history is not.
        if (recent and recent[0].get("role") == "tool" and to_compress
                and to_compress[-1].get("tool_calls")):
            recent.insert(0, to_compress.pop())

    if not to_compress:
        return messages

    # What the summarizer reads of each message: all of it while it fits, and
    # the longest cut first when it does not - see _RATIO. A fixed cut per
    # message is still there for whoever sets MESSAGE_COMPRESS_TRUNC.
    fixed = int(getattr(config, "MESSAGE_COMPRESS_TRUNC", 0) or 0)

    if config.DEBUG:
        print(f"[memory] Compressing {len(to_compress)} messages ({context})...")
    summary = None
    for attempt in range(3):
        text = _text_for(to_compress, _budget_chars(2048, ratio) >> attempt, fixed)
        try:
            summary = summarize(text, context, model=model)
            break
        except llm_client.LLMInterrupted:
            raise                   # a stop is a stop, not a failed summary
        except llm_client.ContextOverflow as e:
            why = e                 # it did not fit after all: half as much
        except Exception as e:
            why = e
            break
    if summary is None:
        if config.DEBUG:
            print(f"[memory] summarizer failed ({why}); cutting instead.")
        summary = _cut(to_compress, why)

    summary_msg = {
        "role":    "user",
        "content": f"[SUMMARY OF WHAT HAPPENED SO FAR]:\n{summary}",
    }

    return list(head) + [summary_msg] + recent
