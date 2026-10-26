# 29. The advisor is called by Pragma, not by the agent

- **Date:** 2026-10-26
- **Status:** accepted
- **Where:** [`core/advisor.py`](../../core/advisor.py), [`core/react.py`](../../core/react.py), [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`agent/chat.py`](../../agent/chat.py)

## Context

A small model run as the agent does the work and misjudges it. Asked for a
snake game, Qwen3.6-35B-A3B delivered one that worked, after 85 steps: some 65
of them went on six variants of the same throwaway terminal script, and at no
point did it stop to ask whether it was getting anywhere.

A second, more capable model can plan the work and advise on it. Anthropic's
API offers this as a tool the agent calls when it wants advice. But the agent
calling for help when it needs it is the very judgement a small model lacks:
left to it, the call would not come when it was needed.

## Decision

An advisor role, served by any endpoint, and turned on per project in
`/settings`: `plan`, or `plan + consult`. Off by default.

- **The plan** is asked for before the first step of every turn, in a fixed
  form with `Done when` first; the advisor answers NO PLAN for a turn that
  needs no work. It is added to the request, which compression never touches.
- **Advice** is asked for by Pragma, on four signals it measures: the same
  call failing again and again, most calls failing, nearly the same command
  run three times, half the steps spent with nothing delivered. A project sets
  how many times a turn may ask; 2 by default.

What the advisor says reaches the agent as a message beginning `[ADVISOR]`,
with its standing in the message itself rather than in the system prompt,
which is fixed for a conversation while the advisor can be turned on in the
middle of one. It is not the person, and cannot allow what only the person
can. It is not the critic either: the critic judges the finished work, the
advisor the start and the middle, and neither sees what the other said.

## Consequences

- A project with the advisor off sends exactly what it sent before.
- Each plan costs a call before the first step, on every turn - also on turns
  that turn out to need none, where the advisor says so in a few tokens.
- With no endpoint given the role, the agent's own model plans for itself.
- On the screen each plan and piece of advice is one line; `/plan` shows them
  whole.
