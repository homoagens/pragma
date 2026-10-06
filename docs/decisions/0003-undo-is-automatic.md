# 3. Undo is automatic

- **Date:** 2026-07-23
- **Status:** accepted
- **Where:** [`core/checkpoint.py`](../../core/checkpoint.py)

## Context

The agent edits real files, and a bad edit had no way back unless the
folder was a git repository and the work had been committed. Many folders are
neither. Without a way back, the only safe strategy is timid edits.

## Decision

The first time a conversation touches a file, the file as it was is copied
aside, under `.pragma_checkpoints/` in the workspace. Nothing has to be
arranged first: a safety net that must be remembered is missing exactly when
it is needed.

Later edits to the same file do not replace that copy. Undoing means going
back to how the file was before the conversation, not before the last of
several edits.

## Consequences

- An ambitious change is affordable, because it can be taken back.
- Only edits made through the file tools can be undone. What a shell command
  did to a file cannot.
