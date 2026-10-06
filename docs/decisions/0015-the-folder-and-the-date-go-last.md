# 15. The folder and the date go last in the prompt

- **Date:** 2026-10-01
- **Status:** accepted
- **Where:** [`agent/prompts.py`](../../agent/prompts.py)

## Context

A model server keeps what it has already read and reuses it when the next
request starts the same way. The agent's system prompt named the working
folder and today's date a third of the way down, so two sessions shared only
the part above that line: every new conversation made the server read almost
the whole prompt again before the first answer.

## Decision

Everything that is the same from one session to the next comes first. The
folder and the date are a block of their own, appended last, after the
project's rules.

## Consequences

- The first answer of a new conversation arrives in a fraction of the time
  it took.
- Anything added to the prompt later has to respect the same order: what
  changes between sessions goes at the end.
