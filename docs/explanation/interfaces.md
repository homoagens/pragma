# Three interfaces, and where each stands

Pragma can be used in three ways. They are not equals, and these pages do
not pretend they are.

| Interface | Where it stands |
|---|---|
| **The terminal on Linux** | Where Pragma is developed, and where everything is tested. New work lands here first. |
| **The terminal on Windows** | The same screens, drawn from PowerShell. It is brought into line with Linux after each round of changes, so it can be a step behind. |
| **The browser** | The old interface. It still runs, it has not followed the terminal, and it is not being worked on for now. |

**Unless a page says otherwise, what it describes was tried in the terminal
on Linux.** Where Windows is known to differ, the page has a section for it.
What a page says about Windows comes from reading the Windows launcher's
code; it was not tried there for that page.

macOS runs the Linux launcher. It is not what Pragma is tested on.

## The terminal on Linux

Start it with `pragma`. The launcher is
[`tools/pragma_launcher.py`](../../tools/pragma_launcher.py), and a project
opens into [`agent/chat.py`](../../agent/chat.py).

This is the reference. The [tutorial](../tutorial/first-project.md) and every
guide were run here, and CI — the checks made on every push — runs on Linux
too.

## The terminal on Windows

Start it with `pragma` in PowerShell. The launcher is
[`tools/Pragma.psm1`](../../tools/Pragma.psm1).

Most of what you see is the very same code as on Linux: the home prompt,
`/configure`, the briefing, `/jobs` and the conversation itself are single
Python programs that both launchers call. The list of projects and the memory
itself have one format, so a memory written on one system can be read on the
other.

What the Windows launcher does with code of its own is where it can differ:

| What | On Linux | On Windows |
|---|---|---|
| Snapshots of a project's memory | `~/.pragma/projects/backups/<name>/`, the memory only | `~/.pragma/backups/<name>/`, the memory, the workspace or both, in another layout. [Details](../how-to/back-up-and-restore-memory.md) |
| A project's own settings | the steps per turn and how much is recalled, from `/settings` | the same page, not yet looked at there, plus `pragma -Set <key> <value>` for the others |
| The tools the agent is given | 14: reading and searching are left to the shell | all 20. [Which ones](../reference/skills.md) |
| Installing | `./install.sh` | `.\install.ps1` |

A change made on Linux reaches Windows when the two are next aligned. Until
then the newest behaviour may be missing there, or untried.

## The browser

Start it with `python -m agent.run`, from Pragma's own environment, or with
`pragma-gui.bat` on Windows. It opens at `http://localhost:8006`.

It is the interface Pragma had before the terminal one, and it has stayed
where it was. It runs the same loop and offers the agent the same tools, but
little of what these pages describe applies to it:

- It has threads, not projects: there is no home screen, no briefing and no
  `/configure`.
- It does not read a project's [`PRAGMA.md`](../how-to/write-project-rules.md).
- It does not write episodes. Of the memory it uses only the beliefs, which
  it finds by keyword and adds to after a task.

Treat it as a view of an earlier Pragma, not as a second way to work. It is
kept because it still runs; when it is taken up again, this page will say so.

## One more way in, the same everywhere

A [single task](../how-to/run-one-task.md) with no interface at all,
`python -m agent.batch`, is plain Python and does not depend on either
launcher. It reads `PRAGMA.md`, and uses memory when asked to.
