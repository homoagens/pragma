# 30. One rule for every page: ←→ changes, Enter opens

- **Date:** 2026-10-26
- **Status:** accepted
- **Where:** [`terminal/pragma_configure.py`](../../terminal/pragma_configure.py), [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`terminal/pragma_menu.py`](../../terminal/pragma_menu.py), [`core/config.py`](../../core/config.py)

## Context

`/configure` had grown around its servers. Which model answered a role, and
whether it reasoned there, was asked on each server's page - `serves`, `who
reasons`, `effort` - so "which model plans, and does it think?" had its
answer spread over two servers' pages, each listing every role. A first
rework gave each role a page of its own, and it was no better: choosing a
role's model left you on that page, to be backed out of before the next role.
Servers that were down were drawn as large as those that were up, and offered
as models. `/settings` had grown to nine rows, four of them the levels of one
thing, and the critic was switched on for the machine while the advisor, its
counterpart at the start of a turn, was switched on per project.

## Decision

One rule on every page: **↑↓ chooses a row, ←→ changes its value where it has
one, Enter opens what is a list or has to be typed.** Every change is one key,
and nothing is entered that has to be left to change the next thing.

- `/configure` is a table of **who does what**: each role, its model, how it
  thinks. ←→ changes how it thinks - `think` or `no-think`, or on Claude the
  effort, `low` to `max`, per role, so the same Claude can think little as the
  recall and hard as the advisor. Enter chooses its model from the servers
  that are **up**, and comes back to the table. Under it, `servers` - up first,
  then `add`, then those that are down, there because a wrong address is the
  usual reason one is down - and `this machine`, the switches of the whole
  machine. A server's page asks only about the machine. What is stored has not
  changed.
- The **critic** is turned on per project, like the advisor. `CRITIC` in the
  environment still outranks it for a run, and a project that never chose
  follows the switch the machine used to have. **Prediction** stays the
  machine's: it is about how you like to type, not about a project.
- `/settings` has one row per thing a project decides: steps (←→ by ten),
  advisor (off, plan, plan + consult), consults per turn, critic, memory
  (few, medium, many - its four levels one Enter away), rule packs, commands
  allowed.

## Consequences

- No catalogue and no project needs converting.
- A machine that had the critic on keeps it on in every project that has not
  chosen; the switch itself is no longer on any page.
- `memory` stays one role for the four faculties that write the memory.
- A terminal that cannot go raw gets numbered lists, and changes a value by
  opening its row.
