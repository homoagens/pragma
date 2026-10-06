# 12. On Unix the shell is the tool

- **Date:** 2026-09-24
- **Status:** accepted
- **Where:** [`core/skills/__init__.py`](../../core/skills/__init__.py)

## Context

Pragma offered the agent its own skills for reading a file, listing a
folder and searching text, and also a shell. The prompt said to prefer the
shell on systems that have a good one. The model kept reaching for the
dedicated skill anyway: a rule written in prose loses to a list of tools
every time.

## Decision

On Linux and macOS the skills a shell already does better are not offered at
all: reading, listing, finding, searching, and the two for git. `grep`,
`find`, `sed` and `git` answer in one call what those answered in several,
and they compose.

Everything that *writes* stays, on every system, because undo works by
copying a file before a file tool touches it, and a shell command does not
pass through that. On Windows the whole list stays: its shell has no
equivalent.

## Consequences

- What the agent is told to do and what it is given to do it with agree.
- The list of tools depends on the system, which the
  [skills reference](../reference/skills.md) marks.
