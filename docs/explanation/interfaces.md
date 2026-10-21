# The interfaces, and where each stands

Pragma is used from a terminal, on Linux or on Windows. The two are not
equals, and these pages do not pretend they are.

| Interface | Where it stands |
|---|---|
| **The terminal on Linux** | Where Pragma is developed, and where everything is tested. New work lands here first. |
| **The terminal on Windows** | The same screens, drawn from PowerShell. It is brought into line with Linux after each round of changes, so it can be a step behind. |

**Unless a page says otherwise, what it describes was tried in the terminal
on Linux.** Where Windows is known to differ, the page has a section for it.
What a page says about Windows comes from reading the Windows launcher's
code; it was not tried there for that page.

macOS runs the Linux launcher. It is not what Pragma is tested on.

## The terminal on Linux

Start it with `pragma`, or `pragma --agent` for the agent without memory. The
launcher is [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py),
and a project opens into [`agent/chat.py`](../../agent/chat.py).

This is the reference. The [tutorial](../tutorial/first-project.md) and every
guide were run here, and CI — the checks made on every push — runs on Linux
too.

## The terminal on Windows

Start it with `pragma` in PowerShell. The launcher is
[`terminal/Pragma.psm1`](../../terminal/Pragma.psm1).

Most of what you see is the very same code as on Linux: the home prompt,
`/configure`, the briefing, `/jobs` and the conversation itself are single
Python programs that both launchers call. The list of projects and the memory
itself have one format, so a memory written on one system can be read on the
other.

What the Windows launcher does with code of its own is where it can differ:

| What | On Linux | On Windows |
|---|---|---|
| Snapshots of a project's memory | `~/.pragma/projects/backups/<name>/`, the memory only | `~/.pragma/backups/<name>/`, the memory, the workspace or both, in another layout. [Details](../how-to/back-up-and-restore-memory.md) |
| A project's own settings | the steps per turn, the commands allowed without asking and how much is recalled, from `/settings` | the same page, not yet looked at there, plus `pragma -Set <key> <value>` for the others |
| The tools the agent is given | 15: reading and searching are left to the shell | all 21. [Which ones](../reference/tools.md) |
| The [agent without memory](../how-to/use-the-agent-alone.md) | `pragma --agent` | not there: the launcher does not have the flag |
| [Serving a project](../how-to/serve-a-project.md) to another program | `/serve` | not there: the home screen does not offer it |
| Installing | `./install.sh` | `.\install.ps1` |

The [commands that wait for you](../how-to/allow-commands.md), the
[MCP servers](../how-to/use-mcp-servers.md), `/compact` and pictures drawn
in the terminal are the conversation's own code, the same on both; on
Windows they have been read, not tried.

A change made on Linux reaches Windows when the two are next aligned. Until
then the newest behaviour may be missing there, or untried.

## One more way in, the same everywhere

A [single task](../how-to/run-one-task.md) with no interface at all,
`python -m agent.batch`, is plain Python and does not depend on either
launcher. It reads `PRAGMA.md`, and uses memory when asked to.
