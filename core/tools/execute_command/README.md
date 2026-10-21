# execute_command

Run a shell command and return its stdout, stderr and exit code. Each call is a new process: pass `cwd`, since `cd` does not carry over. Nothing can be typed at it: a program waiting for input meets the end of it at once. Anything meant to keep running - a server, a watcher - goes with `background=true`, or it ends only at the timeout.

---

## Parameters

- `command` (str): Shell command to run, by `/bin/sh`.
- `cwd` (str, optional, default ""): Working directory; defaults to process cwd.
- `timeout` (int, optional, default 60): Seconds before the process tree is killed.
- `capture_stderr` (bool, optional, default True): Include stderr in the output.
- `max_output_chars` (int, optional, default 10000): Truncate stdout/stderr if longer.
- `background` (bool, optional, default False): Start it and return at once, with its PID, a log file and the command that stops it.
- `stop_event` (optional): threading.Event; if set mid-run, kills the process immediately.

## Returns

Formatted string with `returncode`, `stdout`, and `stderr` sections, or timeout/interrupt notices, or `"ERROR: ..."`.

## Notes

- A timeout or a stop kills the command's whole process group, not only the shell.
- A command has nothing on its input and no terminal behind it: one that asks for input (`input()`) meets the end of it at once, and one that draws a screen and waits for keys (curses, pygame) can only run into the timeout.
- The shell is the first tool for looking: `ls`, `find`, `grep -rn`, `sed -n '120,180p' FILE`, `git status`, `git diff`.

## Examples

```json
{ "action": "execute_command", "args": { "command": "python3 script.py", "cwd": "/home/me/project" } }
{ "action": "execute_command", "args": { "command": "grep -rn 'def main' src/", "cwd": "/home/me/project" } }
{ "action": "execute_command", "args": { "command": "python3 -m http.server 8000", "cwd": "/home/me/project", "background": true } }
```

When project instructions name an interpreter — a virtual environment, a
specific path — use that instead, in every call including a one-line syntax
check:

```json
{ "action": "execute_command", "args": { "command": "venv/bin/python -m py_compile script.py", "cwd": "/home/me/project" } }
```

## Do not

- Ignore a project-specified interpreter because the command felt too small to matter — a throwaway check run against the wrong Python is still the wrong Python
- Omit `cwd` when running scripts — without it the command runs in Pragma's directory, not the user's project
- Chain directory changes with `&&` across calls: each call is a fresh subprocess — use `cwd` instead
- Rely on environment state from a previous call — every `execute_command` is an independent subprocess
