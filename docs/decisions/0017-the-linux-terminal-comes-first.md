# 17. The Linux terminal comes first

- **Date:** 2026-10-06
- **Status:** accepted
- **Where:** [`tools/pragma_launcher.py`](../../tools/pragma_launcher.py), [`tools/Pragma.psm1`](../../tools/Pragma.psm1), [`agent/server.py`](../../agent/server.py)

## Context

Pragma has three interfaces, written at three different times: a browser
interface, a terminal launcher in PowerShell for Windows, and a terminal
launcher in Python for Linux and macOS. Keeping three in step means every
change is made, and tried, three times — or is made once and quietly missing
from the other two. Both had started to happen, and nothing said which
interface was the one to trust.

## Decision

Pragma is developed in the terminal on Linux, and tested there.

The terminal on Windows follows. It is brought into line with Linux after
each round of changes, not during it.

The browser interface is left as it is. It still runs, and it is not being
worked on for now.

## Consequences

- The documentation describes the terminal on Linux. Where Windows is known
  to differ, the page says so; where a page says nothing, it was not tried
  on Windows.
- Windows can be a step behind, and a behaviour that is new on Linux may be
  missing or untried there until the next alignment.
- What the two launchers each do with their own code can drift, and has: the
  snapshots of a project's memory are kept in different places and laid out
  differently.
- The browser interface does not read a project's rules file and does not
  write episodes. That is stated, not fixed.
- [Three interfaces, and where each stands](../explanation/interfaces.md) is
  kept current with all of this.
