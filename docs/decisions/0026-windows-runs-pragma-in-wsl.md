# 26. Windows runs Pragma inside WSL

- **Date:** 2026-10-21
- **Status:** accepted
- **Where:** [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`core/tools/__init__.py`](../../core/tools/__init__.py), [`agent/prompts.py`](../../agent/prompts.py)

## Context

There were two launchers, one in PowerShell for Windows and one in Python
for Linux and macOS, built from shared pieces
([10](0010-one-set-of-screens-for-every-system.md)). Linux came first and
Windows followed ([17](0017-the-linux-terminal-comes-first.md)), which in
practice meant Windows was always a step behind: no `/serve`, no agent
alone, snapshots in another place and another layout, and every change
there described from the code rather than tried.

Six skills — reading a file, listing a folder, globbing, grepping, asking
git for its status and its diff — existed only because cmd.exe has no shell
to do those things; on Linux and macOS they were never offered
([12](0012-on-unix-the-shell-is-the-tool.md)).

## Decision

The PowerShell launcher is removed, and with it the installer for Windows,
its double-click starters and the endpoint dashboard it opened. On Windows,
Pragma runs inside WSL: it is the Linux Pragma, installed and started the
same way.

The six skills go with it: the shell reads, lists, searches and asks git,
everywhere. So do the branches of code written for the Windows console.

## Consequences

- One launcher, one way to install, one place for snapshots; a change is
  tried where it runs.
- The agent's palette is the same on every system, and so is its prompt.
- Projects made with the Windows launcher stay where it left them, in the
  Windows home folder; [Move a project](../how-to/move-a-project.md) brings
  one into WSL.
