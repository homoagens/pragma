# execute_command

Execute a shell command and return its stdout, stderr, and return code.

---

## Parameters

- `command` (str): Shell command to run. Uses cmd.exe on Windows, /bin/sh on Linux/macOS.
- `cwd` (str, optional, default ""): Working directory; defaults to process cwd.
- `timeout` (int, optional, default 60): Seconds before the process tree is killed.
- `capture_stderr` (bool, optional, default True): Include stderr in the output.
- `max_output_chars` (int, optional, default 10000): Truncate stdout/stderr if longer.
- `stop_event` (optional): threading.Event; if set mid-run, kills the process immediately.

## Returns

Formatted string with `returncode`, `stdout`, and `stderr` sections, or timeout/interrupt notices, or `"ERROR: ..."`.

## Notes

- On Windows, uses `taskkill /F /T` to kill the entire process tree; on POSIX, kills the process group.
- A command has nothing on its input and no terminal behind it: one that asks for input (`input()`) meets the end of it at once, and one that draws a screen and waits for keys (curses, pygame) can only run into the timeout.
- Commands are not portable across platforms: use `python`/`git`/`pip` for portability.

## Examples

```json
{ "action": "execute_command", "args": { "command": "python script.py", "cwd": "C:\\project" } }
{ "action": "execute_command", "args": { "command": "pip install requests", "cwd": "C:\\project", "timeout": 120 } }
{ "action": "execute_command", "args": { "command": "python -m pytest tests\\", "cwd": "C:\\project" } }
```

The interpreter above is the platform default. When project instructions name
one — a virtual environment, a specific path — use that instead, in every call
including a one-line syntax check:

```json
{ "action": "execute_command", "args": { "command": ".\\venv\\Scripts\\python.exe -m py_compile script.py", "cwd": "C:\\project" } }
```

## Do not

- Ignore a project-specified interpreter because the command felt too small to matter — a throwaway check run against the wrong Python is still the wrong Python
- Omit `cwd` when running scripts — without it the command runs in the server's directory, not the user's project
- Use Unix commands: no `ls`, `cat`, `rm`, `grep`, `find`, `touch` — use filesystem skills or Windows equivalents
- Run scripts that call `input()` or wait for stdin — they hang forever; remove `input()` or pipe the value
- Chain directory changes with `&&`: `cd foo && python x.py` fails because each call is a fresh subprocess — use `cwd` instead
- Rely on environment state from a previous call — every `execute_command` is an independent subprocess
