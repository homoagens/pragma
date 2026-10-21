# Let a project run some commands without asking

*For the terminal. Tried on Linux; [what differs on Windows](../explanation/interfaces.md).*

In a conversation, a command that cannot be undone waits for your yes. In a
project where some of those are routine — clearing `build/`, pushing,
installing from `requirements.txt` — the question can be answered once, for
good.

## What waits for you

A file the agent changes with its own tools is copied aside first, so the
session's edits can be undone. A command run through the shell passes no
such point, so these are held until you allow them:

- deleting files;
- git that throws history away or sends it: `push`, `reset --hard`, `clean`,
  `checkout --`, `restore`, `branch -D`, `stash drop`;
- installing or removing software, with any package manager;
- a script downloaded and piped straight into a shell;
- anything run with `sudo`.

The question shows the command and why it is held. **Yes** runs it. Anything
else, and it is not run: the agent is told not to do the same thing another
way, to carry on without it and to say in its answer what was not done, and
the step reads `not allowed`.

The command is read as text, and the reading errs towards asking, so now
and then something harmless is held. What it cannot see is a command that
destroys without saying so — a script that deletes when it runs, output
redirected over a file — which is why the agent is also told not to do such
things on a guess.

A [single task](run-one-task.md) run from a script has nobody to ask, and is
not held.

## Allow a command for one project

Inside the project, `/settings`, then `commands allowed`, then `add a
pattern`, and type it. It counts from the next command, in this project only.

A pattern is compared word by word with one command at a time:

| Pattern | Allows | Does not allow |
|---|---|---|
| `rm build/*` | `rm build/a.o` | `rm build/sub/a.o`, `rm build/a.o x` |
| `rm build/**` | anything under `build/`, at any depth | |
| `git push *` | `git push` with any further words | |

`*` inside a word stops at a `/`; `**` does not; `*` as the last word takes
any number of further words. A line that chains several commands runs
unasked only if every held command in it is covered.

Paths are compared as the project names them. The agent usually writes
paths in full, so a path inside the project's folder is also tried relative
to it: `rm build/*` covers `rm /home/you/first/build/a.o`. A path outside the
folder keeps its own spelling, and a pattern has to name it to cover it.

**Be specific.** A pattern allows exactly what it says, and nothing asks
again.

## Take one away

`/settings`, `commands allowed`, and Enter on the pattern. From the next
command it asks again.

The patterns are kept with the project's settings in the registry, as
`AllowedCommands`: [Files](../reference/files.md) has where.
