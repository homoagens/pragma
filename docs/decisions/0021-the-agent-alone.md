# 21. The agent can run alone

- **Date:** 2026-10-13
- **Status:** accepted
- **Where:** [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`terminal/pragma_menu.py`](../../terminal/pragma_menu.py), [`agent/chat.py`](../../agent/chat.py)

## Context

A conversation could always run without the memory, but the launcher asked
for the memory every time, so there was no way to get there from `pragma`.
On a machine whose model is slow, the calls around a turn — the recall
before it, the writing after the conversation — can cost more than the
turn.

## Decision

`pragma --agent` starts every project of that run with the agent alone:
nothing is recalled before a turn, and nothing is written to memory after
the conversation. The stores are left as they are, and the next run without
the flag is as before.

The flag is kept in the environment as `PRAGMA_AGENT`, because the home
screen, the briefing and the conversation are three programs and each has to
know. Each page leaves out what there is nothing to do with in that run, and
says the memory is off where it would have spoken of it.

## Consequences

- `/memory` and `/jobs` still answer when typed: a memory written by an
  earlier run may still be at work.
- `/configure` and `/status` show only the roles still asked something.
- Linux and macOS only: the Windows launcher does not have the flag.
