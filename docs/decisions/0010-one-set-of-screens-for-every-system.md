# 10. One set of screens for every system

- **Date:** 2026-09-20
- **Status:** accepted
- **Where:** [`tools/pragma_launcher.py`](../../tools/pragma_launcher.py), [`tools/Pragma.psm1`](../../tools/Pragma.psm1)

## Context

The launcher was written in PowerShell, for Windows, while everything it
started was Python that already ran anywhere. Running Pragma on a Linux
machine — often the one holding the model — meant having no projects, no
briefing and no pages.

## Decision

The launcher exists twice, in PowerShell and in Python, and both are built
from the same pieces: the home prompt, the `/configure` pages, the briefing
and the record of background work are single Python programs that both call.
The list of projects is one file with one format, so a project made on one
system opens on another.

## Consequences

- A screen is implemented once wherever that was possible, and behaves the
  same everywhere.
- Where the two launchers each have their own code, they can drift. The
  snapshots of a project's memory are where they have.
