# 6. The server is asked for its context window

- **Date:** 2026-09-05
- **Status:** accepted
- **Where:** [`core/config.py`](../../core/config.py)

## Context

Pragma decides when to compact a conversation from the size of the model's
context window. That size was a number in a file. When it was wrong, nothing
degraded gracefully: Pragma went on talking until the server refused the
request, having planned for a window it never had.

## Decision

An empty `CONTEXT_WINDOW` means *ask the server*. llama.cpp reports the
window per slot, so the arithmetic of dividing by the number of slots is
already done by the one who knows.

A number someone wrote still wins: a project's own setting, then the
environment, then the server, then a default.

## Consequences

- Restarting the server with another context or another number of slots
  is picked up by the next conversation with no file to edit.
- A server that does not report its window falls back to the default, and
  the briefing warns when the two disagree.
