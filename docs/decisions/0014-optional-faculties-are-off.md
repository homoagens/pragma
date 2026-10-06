# 14. Optional faculties are off, and chosen once for the machine

- **Date:** 2026-09-25
- **Status:** accepted
- **Where:** [`core/config.py`](../../core/config.py), [`core/suggest.py`](../../core/suggest.py), [`tools/pragma_configure.py`](../../tools/pragma_configure.py)

## Context

Some things Pragma can do cost one more model call on every turn, on a
local server that is shared with everything else. Whether they are worth
that depends on how someone likes to work, not on what they are working on.

## Decision

A faculty of that kind is off unless it is asked for. It is asked for once,
in `/configure`, for the whole machine — not per project, where the same
question would have to be answered again each time.

An environment variable overrides the choice for a single run.

## Consequences

- A new installation makes no call the person did not ask for.
- Adding a faculty of this kind means adding one line to `/configure` and
  one variable, nothing per project.
