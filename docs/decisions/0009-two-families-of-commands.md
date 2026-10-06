# 9. Two families of commands, not twenty commands

- **Date:** 2026-09-16
- **Status:** accepted
- **Where:** [`agent/chat.py`](../../agent/chat.py), [`tools/pragma_home.py`](../../tools/pragma_home.py)

## Context

Inside a conversation there were some twenty commands in one flat list. The
one used daily and the one used twice a year weighed the same, and the help
was a wall.

## Decision

What is done *inside* a project and what is done *to* a project are
separated. A conversation keeps the first: `/memory` with its views, and a
handful of others. Starting, backing up and deleting a project live on the
home screen, where no project is open.

Every old name still works and is offered by nothing. A command typed in the
wrong place says where it went.

## Consequences

- The list a person reads is seven lines long.
- A habit is never broken by a reorganisation: the old names are kept as
  aliases for good.
