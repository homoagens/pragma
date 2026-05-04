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
- Commands waiting for user input (input()) will time out — remove interactive calls before using.
- Commands are not portable across platforms: use `python`/`git`/`pip` for portability.
