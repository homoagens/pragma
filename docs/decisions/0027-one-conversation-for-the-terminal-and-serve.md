# 27. One conversation, for the terminal and for /serve

- **Date:** 2026-10-21
- **Status:** accepted
- **Where:** [`agent/conversation.py`](../../agent/conversation.py), [`agent/chat.py`](../../agent/chat.py), [`agent/serve.py`](../../agent/serve.py)

## Context

A conversation in the terminal and a project served to another program
([24](0024-a-project-can-be-served.md)) hold the same kind of conversation:
the memory recalled before each turn, the turns recorded, the context
compacted when it fills up, what was said handed to the memory at the end.
It was written twice. /serve borrowed seven private pieces of the chat for
it and wrote the rest again, and in four places it had drifted from the
chat without anyone deciding so: it did not pass on the weight the server
had counted, so every turn started from an estimate; a compaction in the
middle of a turn emptied the whole desk of recalled memories, so the next
turn recalled and reinforced them again; it judged a conversation full by
the largest request of a turn rather than the last; and it ignored
`CHAT_COMPACT_MODE`.

## Decision

The conversation is written once, as `Conversation` in
`agent/conversation.py`: the turn, the compactions, the handing over to
memory, and the state they share. The chat keeps what a person at a
terminal adds to it - the prompt, the commands, ctrl+C and ctrl+D around a
turn, the screen. /serve keeps what a program adds - the words sent so far,
by which its next request is recognised, one turn at a time, the idle close,
the program's context cut to fit.

## Consequences

- A change to recall, compaction or memory is made in one place and holds
  for both.
- The four differences are gone: /serve now does what the chat does.
- A turn stopped before it reached the model is kept for the memory in
  /serve too, as it always was in the chat.
