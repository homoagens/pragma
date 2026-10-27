# 32. A send-back has its own consult

- **Date:** 2026-10-27
- **Status:** accepted; amends [31](0031-the-critic-holds-the-work-to-the-plan.md)
- **Where:** [`core/react.py`](../../core/react.py), [`core/advisor.py`](../../core/advisor.py)

## Context

[31](0031-the-critic-holds-the-work-to-the-plan.md) had the advisor called
when the critic sends the work back, and counted that call against the
turn's consults - two unless a project says otherwise. In a long turn the
watchdogs spent both before the work was delivered, so when the critic spoke
the advisor could not: the send-back reached the agent alone, which is what
31 was meant to end.

## Decision

The consult a send-back calls is not one of the turn's consults. Those are
for an agent that has got stuck, and the project sets how many it may have;
a send-back is the critic's, and is already bounded by how many times the
critic may send work back (`CRITIC_MAX_ROUNDS`, 2). With the advisor on
`plan + consult`, every send-back calls it.

## Consequences

- A turn can now make up to two more advisor calls than its consults per
  turn, one for each send-back.
- `plan` alone still never consults.
