# Write rules for a project

*For the terminal. Tried on Linux; [what differs on Windows and in the browser](../explanation/interfaces.md).*

Memory is what the agent *learns*, and it can fade. A rule you want followed
on every task, without exception, is something you *decide* — and it goes in
a file.

## Write the file

Create `PRAGMA.md` in the root of the project's folder, with any editor, and
write the rules in plain language:

```markdown
# Rules for this project

- Use the Python interpreter in ./venv, never the system one.
- Never run `git push`. Commit, and tell me.
- Tests live in tests/ and are run with `pytest -q`.
```

There is no format to follow. Short, direct sentences work best.

## When it takes effect

The file is read when the project is opened. A rule added while a
conversation is running applies from the next time you open the project:
**ctrl+D**, then `/open` it again.

## What it does

The rules are handed to the agent as standing instructions, above everything
else it has been told, and they apply to every action — including the quick
ones it might think too small to matter. Where a rule disagrees with one of
Pragma's own defaults, the rule wins.

They do not compete with memory. Whatever the agent recalls for a turn is
placed beside your request; the rules are part of what it is, on every turn.

## What the agent cannot do

It cannot create, change or delete `PRAGMA.md`. The file-writing tools refuse
that name outright, in every folder, so the agent can never grant itself a
permission. If a rule should change, the agent tells you what to change and
you edit the file.

## Details

- Only the first 4000 characters are used; the setting is
  [`PRAGMA_MD_MAX_CHARS`](../reference/configuration.md#budgets). A rules
  file that long is usually better split into fewer, sharper rules.
- An HTML comment (`<!-- like this -->`) is a note to yourself: it is removed
  before the agent sees the file. A file holding only comments counts as
  empty.
- It applies the same way to a conversation and to a
  [single run](run-one-task.md). The browser interface does not read it.
