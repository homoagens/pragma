# 24. A project can be served to other programs

- **Date:** 2026-10-15
- **Status:** accepted
- **Where:** [`agent/serve.py`](../../agent/serve.py), [`terminal/pragma_serve.py`](../../terminal/pragma_serve.py), [`terminal/pragma_home.py`](../../terminal/pragma_home.py)

## Context

Pragma could be used from its own terminal only. Programs that already talk
to a model — a chat panel, a presentation tool — had no way to use a project,
its memory and its tools, short of being rewritten around Pragma.

The other way round was considered: Pragma offered to another agent as a
tool, over MCP. It was not chosen. The agent calling the tool would decide
what Pragma is asked and when, and the memory would be written from what that
agent chose to pass on. Pragma would no longer be the one living the
conversation it remembers.

## Decision

A project can be served as an OpenAI-compatible endpoint. A program is
pointed at it with the three settings it would use for a model — an address,
a model name, a key — and gets the whole of Pragma, which stays in charge of
the turn: the recall, the agent, the memory written when the conversation
ends. Pragma, in turn, can use any model in `/configure`, a stronger one
included.

- **One process, one port, one project.** A process is started for each
  served project, with that project's environment, so one project's memory
  can never be written into another's, and the port alone chooses the
  project.
- **They outlive the window.** A program should not stop working because a
  terminal was closed. What is served is a list with each project on or off;
  the home screen says every time it is drawn which are on and whether they
  run; the next `pragma` starts again what is on and is not.
- **The program's system messages are context, not memory.** They reach the
  agent for that turn only.
- **Nobody can answer mid-turn.** The agent asks in its reply instead, and a
  command that cannot be undone runs only if the project allows it.
- **A key per project.** A program on this machine may send none; an address
  opened to the network refuses a request without it.

## Consequences

- One conversation at a time per project: a program that starts over closes
  the one before, which goes to the memory.
- The answer arrives whole at the end of the turn; only what Pragma is doing
  streams while it works.
- Linux and macOS only: the Windows launcher has no `/serve`.
