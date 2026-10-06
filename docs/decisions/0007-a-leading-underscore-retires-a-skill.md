# 7. A leading underscore retires a skill

- **Date:** 2026-09-10
- **Status:** accepted
- **Where:** [`core/skills/__init__.py`](../../core/skills/__init__.py)

## Context

Skills are found by folder. Over time some stopped being used, and some
were never meant for the agent at all: they are the machinery that reads and
writes memory around a turn, kept among the skills because they are loaded
the same way. Each way of running Pragma hid those on its own, and one of
them did not.

## Decision

Two rules, both in the loader.

A folder whose name starts with an underscore is not loaded. Retiring a skill
is renaming its folder; nothing is deleted, and the history of why stays
beside it.

What the harness uses for itself is loaded and never offered. The list of
those names lives in one place, and every way of running Pragma asks the
loader what to offer.

## Consequences

- A tool that is offered is a tool that gets used, so what is offered is
  decided once and not per entry point.
- Bringing a retired skill back is a rename.
