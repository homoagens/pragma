# 4. A project is a folder, and a memory kept apart from it

- **Date:** 2026-09-03
- **Status:** accepted
- **Where:** [`tools/pragma_launcher.py`](../../tools/pragma_launcher.py), [`tools/Pragma.psm1`](../../tools/Pragma.psm1)

## Context

Pragma was started once per session, each from its own script and its own
folder, with the files being worked on and the memory as two subfolders of
it. Working on two things meant two setups, and the memory sat beside the
work.

## Decision

One command, `pragma`, and many projects. A project is a folder to work in
plus a memory of its own, tied together by one entry in
`~/.pragma/registry.json`.

The memory is never inside the folder. It lives under
`~/.pragma/projects/<name>`, because a folder someone works in is often a git
repository, and what a person said to an agent has no business in one.

## Consequences

- Opening a project decides which memory is in use. Two projects never
  share one.
- Moving a project means moving two folders and an entry. There is no
  command for that yet.
