# 25. What is not used is removed

- **Date:** 2026-10-21
- **Status:** accepted
- **Where:** [`core/tools/__init__.py`](../../core/tools/__init__.py), [`requirements.txt`](../../requirements.txt), [`agent/chat.py`](../../agent/chat.py)

## Context

Two things had been kept in the tree after they stopped being used.

The browser interface had stayed where it was when the terminal took over
([17](0017-the-linux-terminal-comes-first.md)): threads instead of projects,
no rules file, no episodes, and a recall of its own that found beliefs by
keyword without the curator. It made everyone install a web server, and two
skills existed only for it.

Retired skills were renamed rather than deleted
([7](0007-a-leading-underscore-retires-a-skill.md)), so that the history of
why stayed beside them. Fifteen of them did, never loaded, together with a
recall skill that was loaded and never called.

## Decision

Both are removed. A skill that is no longer used is deleted, not renamed:
git keeps it, and its history with it. A leading underscore still means
*not a skill*, for the template a new one starts from.

The switch that brought back the conversation's earlier look goes too: that
look is now only what the ledger is built on.

## Consequences

- Pragma is the terminal, on Linux and on Windows. Installing it no longer
  brings a web server.
- What reaches the agent from memory has one way in: the curator.
- Bringing back a removed skill, or the browser, is a checkout from git
  history, not a rename.
