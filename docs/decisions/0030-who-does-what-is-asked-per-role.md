# 30. Who does what is asked per role, and helpers are a project's

- **Date:** 2026-10-26
- **Status:** accepted
- **Where:** [`terminal/pragma_configure.py`](../../terminal/pragma_configure.py), [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`core/config.py`](../../core/config.py)

## Context

`/configure` had grown around its servers. Which model answered a role, and
whether it reasoned there, was asked on each server's page - `serves`, `who
reasons`, `effort` - so "which model plans, and does it think?" had its
answer spread over two servers' pages, each listing every role. Under the
servers sat switches for the whole machine, the critic among them, while the
advisor, the critic's counterpart at the start of a turn, was turned on per
project. `/settings` had grown to nine rows, four of them the levels of one
thing.

## Decision

- `/configure` opens on **who does what**: one row per role, the server that
  answers it and how it thinks there. Enter opens the role's page: `server`,
  and `reasons` - or `effort` on Claude. A server's own page asks only about
  the machine: what it is, what it is for, sampling, name, address, model,
  key. What is stored has not changed: the roles map, and `reasons` and
  `effort` beside the server, per role.
- The **critic** is turned on per project, like the advisor: whether work
  wants checking depends on the work. `CRITIC` in the environment still
  outranks it for a run, and a project that never chose follows the switch
  the machine used to have. **Prediction** stays the machine's: it is about
  how you like to type, not about a project.
- `/settings` has five rows: steps per turn, commands allowed, rule packs,
  **helpers** (the advisor and the critic) and **memory recall** (its four
  levels, one page down).

## Consequences

- No catalogue and no project needs converting.
- A machine that had the critic on keeps it on in every project that has not
  chosen; the switch itself is no longer on any page.
- `memory` stays one role for the four faculties that write the memory.
