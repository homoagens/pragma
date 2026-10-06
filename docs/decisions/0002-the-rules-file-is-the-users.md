# 2. The rules file is the user's, and the agent cannot write it

- **Date:** 2026-07-12
- **Status:** accepted
- **Where:** [`core/config.py`](../../core/config.py), [`agent/prompts.py`](../../agent/prompts.py)

## Context

`PRAGMA.md` holds the rules a person sets for a project, and those rules
can include permissions: what the agent may do without asking. If the agent
could write that file, it could grant itself any of them.

## Decision

`PRAGMA.md` is read-only for the agent. The tools that write files refuse
that name, in any folder, and no setting lifts the refusal — not even the one
that lets a developer edit Pragma's own source.

Its content goes into the system prompt, not into the request: a standing
rule that travels as part of one message loses force as the conversation
grows.

## Consequences

- If a rule should change, the agent says what to change and the person
  edits the file.
- The rules are read when a project opens, so a change takes effect on the
  next opening.
