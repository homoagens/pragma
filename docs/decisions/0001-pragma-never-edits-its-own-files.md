# 1. Pragma never edits its own files

- **Date:** 2026-05-20
- **Status:** accepted
- **Where:** [`core/config.py`](../../core/config.py)

## Context

The agent writes files, and it runs from a folder that is itself full of
files: Pragma's own source, its configuration, its scripts. A request that
wandered there — or a model that decided to "fix" the tool it was running in
— would change the program while it was running, with no review and no way
of knowing afterwards what it had been.

## Decision

Every tool that writes a file refuses any path inside the folder Pragma is
installed in. The folder is worked out from where the code is, so the check
holds wherever Pragma has been cloned. A project cannot be made inside that
folder either.

A developer working on Pragma through Pragma can lift the guard with
`PRAGMA_ALLOW_SELF_MODIFY`. Nothing else does.

## Consequences

- The rule is enforced by the tools, not asked of the model. The system
  prompt says it too, but the prompt is the reminder and the tool is the
  guarantee.
- Pragma cannot be used to develop Pragma without saying so on purpose.
