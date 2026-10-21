# Where Pragma runs

Pragma is a terminal program for Linux. That is where it is developed and
where everything is tested.

| System | How |
|---|---|
| **Linux** | The reference. The [tutorial](../tutorial/first-project.md) and every guide were run here, and CI — the checks made on every push — runs on Linux too. |
| **Windows** | Inside WSL, the Linux that Windows runs beside itself. Pragma there is the Linux one, not a port of it. |
| **macOS** | The same launcher as Linux. It is not what Pragma is tested on. |

**Unless a page says otherwise, what it describes was tried in the terminal
on Linux.**

## Linux

Start it with `pragma`, or `pragma --agent` for the agent without memory. The
launcher is [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py),
and a project opens into [`agent/chat.py`](../../agent/chat.py).

## Windows, inside WSL

Install WSL with a Linux distribution — `wsl --install` in PowerShell does it
once, with Ubuntu — open its terminal, and install Pragma there as on Linux:
`git clone`, `./install.sh`, then `pragma`. Run from Git Bash instead,
`./install.sh` stops and says to use WSL. Its projects and its memory live
in the Linux home folder, `~/.pragma`.

What crosses between the two sides:

- **A model server on Windows.** From WSL, `127.0.0.1` reaches Windows only
  with WSL's *mirrored* networking; otherwise give `/configure` the address
  of the Windows side.
- **A program on Windows using a [served project](../how-to/serve-a-project.md).**
  `127.0.0.1` reaches Pragma in WSL as it is.
- **Files.** The Windows drives are under `/mnt/c`, `/mnt/d`: a workspace can
  be there, though a folder inside WSL is faster.

Pragma once had a launcher of its own for Windows, in PowerShell; it is gone.
Projects made with it are in `C:\Users\<you>\.pragma`, which WSL sees as
`/mnt/c/Users/<you>/.pragma`: [Move a project](../how-to/move-a-project.md)
says how to bring one over.

## One more way in, the same everywhere

A [single task](../how-to/run-one-task.md) with no interface at all,
`python -m agent.batch`, is plain Python and does not depend on the launcher.
It reads `PRAGMA.md`, and uses memory when asked to.
