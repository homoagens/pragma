# 22. Commands that cannot be undone wait for the person

- **Date:** 2026-10-14
- **Status:** accepted
- **Where:** [`core/command_gate.py`](../../core/command_gate.py), [`agent/chat.py`](../../agent/chat.py), [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py)

## Context

The file tools copy a file before they change it, so
[undo is automatic](0003-undo-is-automatic.md). A command run through the
shell passes no such point. The agent is told not to delete, push, install
or run as administrator on a guess — and a model reading "do the action
items in it" took a note's `rm *.py` for permission all the same, the turn
after it had rightly asked about it.

A rule the model is asked to follow depends on the model judging right.

## Decision

In a conversation, the program holds such a command and asks: the command
is shown with the reason it is held, and runs only if the person allows it.
If they do not, the agent is told it was not run and is not to be done
another way, and the step reads `not allowed`. A refusal is final for that
turn, and the guess at the next line never offers consent to one of these.

[`core/command_gate.py`](../../core/command_gate.py) decides which, reading
each command of the line: deleting files, git that throws away or sends
history, installing or removing software, a script piped from the internet
into a shell, anything run with `sudo`. It errs towards asking.

A project can let some run without asking: patterns kept in its settings as
`AllowedCommands`, written from `/settings` and read at every command.

## Consequences

- A single task run from a script is unchanged: nobody is there to ask, and
  its own rule on destructive operations decides.
- What the gate cannot see — a script that deletes when run, output
  redirected over a file — is why the rule in the prompt stays.
- A command that only looks dangerous costs one question.
- [Let a project run some commands without asking](../how-to/allow-commands.md)
  has the patterns.
