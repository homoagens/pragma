# 31. The critic holds the work to the plan, and its revise calls the advisor

- **Date:** 2026-10-27
- **Status:** accepted; amends [29](0029-the-advisor-is-called-by-pragma-not-by-the-agent.md); amended by [32](0032-a-send-back-has-its-own-consult.md)
- **Where:** [`core/critic.py`](../../core/critic.py), [`core/advisor.py`](../../core/advisor.py), [`core/react.py`](../../core/react.py)

## Context

The critic judged a delivery against the request alone, because there was
nothing else to judge it against: judging work against what it was meant to
achieve needs that to have been said before the work began, and nothing said
it. Since [29](0029-the-advisor-is-called-by-pragma-not-by-the-agent.md) the
advisor does, in the plan's `Done when` and `Check`. But the two were kept
apart - neither saw what the other said - so the critic measured the work
against a criterion it had to rebuild from the request, and a revise sent the
work back to the agent alone, the one that had just declared it finished.

## Decision

The planner says what "done" is, the critic holds the work to it, and what
the critic finds is a reason to plan again.

- **The critic reads the plan.** When the turn has one, it is part of what
  the critic is given, after the project's rules: its `Done when` and `Check`
  count among the requirements, and a `Check` the record does not show carried
  out is unverified. The plan serves the request and does not replace it:
  what the request asks and the plan left out is still judged, and what the
  plan adds beyond the request is not.
- **A revise calls the advisor.** With the advisor on `plan + consult` and
  consults left, a send-back is a consult like the others: the advisor reads
  the record and what the critic found, and says whether one step went wrong
  or the plan itself did. Its advice goes to the agent in the same message as
  the critic's. It is counted against the same consults per turn.
- **Neither sees the other's reasoning**, only what it wrote: the critic reads
  the plan, not why it was made; the advisor reads the findings, not the
  critic's thinking.

## Consequences

- A project with the advisor off, or the critic off, sends what it sent
  before.
- With both on, a send-back can cost two calls instead of one.
- `plan` alone still never consults: a revise there goes to the agent as it
  did.
