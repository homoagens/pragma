# Run one task without the terminal interface

*No interface involved: the same on every system. Tried on Linux. [Where each interface stands](../explanation/interfaces.md).*

For a script, a scheduled job, or a task you want to hand over and read the
result of later. One request goes in, the agent works until it has an answer,
and the process ends. Nobody is asked anything on the way.

## Run it

From the folder where Pragma is installed, with Pragma's own Python:

```
venv/bin/python -m agent.batch --task "list every TODO in this repository" --cwd /path/to/project
```

On Windows the interpreter is `venv\Scripts\python.exe`.

The task can also come from a file (`--task-file task.txt`) or from standard
input:

```
echo "summarise CHANGELOG.md in five lines" | venv/bin/python -m agent.batch --cwd /path/to/project
```

`--cwd` is the folder the agent works in. Pragma's own folder is refused.

## Read what happened

Every step is printed as it happens: what the agent did, what came back, and
the conclusion at the end.

| You want | Use |
|---|---|
| to watch it in a terminal | nothing: it is drawn in colour by default |
| a document to read later | redirect it: `> run.md` writes clean Markdown |
| lines a script can search | `--plain`: one `[HH:MM:SS]` line per event |
| everything, untruncated | `--log run.json`: the full record of every step |

The exit code says how it ended:

| Code | Meaning |
|---|---|
| `0` | the agent reached a conclusion |
| `2` | it ran out of steps and was told to conclude with what it had |
| `1` | it failed: no result, the server could not be reached, a bad argument |

## What is different from a conversation

- **Nobody answers questions.** If the agent asks for confirmation, the answer
  is *no*; if it asks anything else, it is told nobody is there and to carry
  on or conclude. Write the task so that it does not need to ask.
- **It takes fewer steps.** The budget is `MAX_STEPS`, 15 unless you say
  otherwise; a conversation opened from the launcher gets 50. Give a long task
  more with `--max-steps 100`.
- **The project's [rules file](write-project-rules.md) still applies.**
  `PRAGMA.md` in the folder given to `--cwd` is read exactly as in a
  conversation.

## With memory

By default a run remembers nothing and is not remembered. Add `--memory` and
it recalls what bears on the task before starting, and writes itself down
when it ends.

Which memory depends on `PRAGMA_DATA_DIR`. Unset, it is `~/.pragma` itself —
a memory of its own, belonging to no project. To run against a project's
memory, name that project's folder:

```
PRAGMA_DATA_DIR=~/.pragma/projects/first venv/bin/python -m agent.batch --memory --task "..." --cwd ~/first
```

In PowerShell the variable is set on a line of its own first:
`$env:PRAGMA_DATA_DIR = "$HOME\.pragma\projects\first"`.

Avoid running it while that project's memory is still being written; `/jobs`
shows when it is.
