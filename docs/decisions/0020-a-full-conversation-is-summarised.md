# 20. A conversation that fills up is summarised

- **Date:** 2026-10-13
- **Status:** accepted
- **Where:** [`agent/chat.py`](../../agent/chat.py)

## Context

A conversation that outgrew the context window had its older turns turned
into memory on the spot, and the last few kept. That needed the memory, and
wrote to it in the middle of a conversation. Nor was there a way to ask for
it before the window was full, or to start over without closing the project.

## Decision

Two commands, and the first also happens on its own.

- `/compact` trades the conversation for one summary, written to go on
  working from. Words after the command say what the summary should take
  care of.
- `/clear` empties the context and starts a new conversation in the same
  project, handing what was said to the memory as closing does. Clearing the
  screen, which `/clear` used to do, is `/clear screen`.

Above `CHAT_COMPACT_TOKENS` — by default `CHAT_COMPACT_PERCENT` of the
window — the conversation is compacted unasked, after a turn or inside one.
Inside a turn, the conversation before the request gives way first, and the
turn's own steps only if that was not enough. A summary that cannot be
written leaves the conversation as it was.

How full the window is comes from what the server last counted, not from an
estimate of characters.

`CHAT_COMPACT_MODE=episodes` restores the previous way.

## Consequences

- Compacting needs no memory, so it works the same with `pragma --agent`.
- Whatever the mode, every turn reaches the memory, whole, when the project
  closes. What the summary leaves out is gone from the context, not from the
  record.
- A summary is written by the model, and is as good as the model.
