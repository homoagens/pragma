# 5. The memory is written by another process

- **Date:** 2026-09-05
- **Status:** accepted
- **Where:** [`tools/pragma_consolidate.py`](../../tools/pragma_consolidate.py), [`tools/pragma_jobs.py`](../../tools/pragma_jobs.py)

## Context

Turning a conversation into memory takes a minute or more of model calls.
It used to happen between closing a conversation and getting the prompt back,
with a spinner. Leaving a room should not take longer than being in it.

A thread would not have been enough: the launcher redraws its screen when the
conversation's process returns, and a thread keeps that process alive.

## Decision

Closing a conversation files a *job* — a file holding the turns to write
down — and starts a separate, detached process to do the work. The terminal
comes back at once.

A job is not a record. One that finishes deletes itself: the episodes are the
record. What stays on disk is what still needs someone — work in flight, and
work that did not finish, with its turns still inside so that it can be run
again.

## Consequences

- Closing a project is instant, and the work survives the terminal being
  closed.
- Work you cannot see is work you cannot trust, so `/jobs` shows it live and
  the next briefing says if something did not finish.
- A model server with one slot serves the worker and the next conversation
  in turn.
