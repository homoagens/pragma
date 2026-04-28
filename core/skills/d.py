# skills/d.py — Deterministic skills [D]
#
# Pure functions: no LLM calls, output is completely reproducible
# given the same input. Testable in isolation without any external service.
#
# Skills covered (12):
#   read_file, write_file, list_dir, glob_match, grep_search,
#   understand_cwd, execute_command, todo_create, session_broadcast,
#   schema_validate, log_event, web_fetch

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests


# ─────────────────────────────────────────────────────────────
# FILESYSTEM
# ─────────────────────────────────────────────────────────────

def read_file(path: str, encoding: str = "utf-8",
              start_line: int = 0, end_line: int = 0) -> str:
    """
    Read the contents of a file.
    start_line / end_line: if both > 0, return only those lines (1-based).
    Returns the content as a string, or an error message.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"
    if start_line > 0 and end_line > 0 and start_line > end_line:
        return f"ERROR: start_line ({start_line}) must be <= end_line ({end_line})"
    try:
        text = p.read_text(encoding=encoding)
        if start_line > 0 and end_line > 0:
            lines = text.splitlines()
            selected = lines[start_line - 1: end_line]
            return "\n".join(selected)
        return text
    except Exception as e:
        return f"ERROR reading {path}: {e}"


def write_file(path: str, content: str, encoding: str = "utf-8",
               create_parents: bool = True) -> str:
    """
    Create or overwrite a file.
    If create_parents=True, creates intermediate directories.
    Returns "OK: written N bytes to <path>" or an error message.
    """
    p = Path(path)
    try:
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"OK: written {len(content.encode(encoding))} bytes to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


def list_dir(path: str = ".", show_hidden: bool = False,
             max_entries: int = 200) -> str:
    """
    List the contents of a directory with metadata (type, size, mtime).
    Returns a tabular string or an error message.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: path not found: {path}"
    if not p.is_dir():
        return f"ERROR: not a directory: {path}"

    entries = []
    for item in sorted(p.iterdir()):
        if not show_hidden and item.name.startswith("."):
            continue
        try:
            stat = item.stat()
            kind = "dir " if item.is_dir() else "file"
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            entries.append(f"{kind}  {size:>10}  {mtime}  {item.name}")
        except Exception:
            entries.append(f"????  {'?':>10}  {'?':>16}  {item.name}")

    if not entries:
        return f"(empty directory: {path})"

    header = f"type       size  modified          name\n{'-'*60}"
    body   = "\n".join(entries[:max_entries])
    suffix = f"\n... ({len(entries) - max_entries} more)" if len(entries) > max_entries else ""
    return f"{header}\n{body}{suffix}"


def glob_match(pattern: str, base_path: str = ".") -> str:
    """
    Find files matching a glob pattern (supports **).
    Example: pattern="**/*.py", base_path="src"
    Returns a list of relative paths separated by newlines.
    """
    base = Path(base_path)
    if not base.exists():
        return f"ERROR: base_path not found: {base_path}"
    try:
        matches = sorted(base.glob(pattern))
        if not matches:
            return f"(no matches for pattern '{pattern}' in '{base_path}')"
        return "\n".join(m.relative_to(base).as_posix() for m in matches)
    except Exception as e:
        return f"ERROR in glob_match: {e}"


def grep_search(pattern: str, path: str = ".", file_glob: str = "*",
                ignore_case: bool = False, max_results: int = 100) -> str:
    """
    Search a regex pattern in file contents.
    path      : directory or single file
    file_glob : filter files (e.g. "*.py", "*.md")
    Returns matches in the format "path:lineno: line_content".
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"ERROR: invalid regex '{pattern}': {e}"

    target = Path(path)
    if not target.exists():
        return f"ERROR: path not found: {path}"

    results: list[str] = []
    is_file = target.is_file()
    files   = [target] if is_file else sorted(target.rglob(file_glob))

    for f in files:
        if not f.is_file():
            continue
        display = str(f) if is_file else f.relative_to(target).as_posix()
        try:
            for lineno, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if regex.search(line):
                    results.append(f"{display}:{lineno}: {line.rstrip()}")
                    if len(results) >= max_results:
                        results.append(f"... (truncated at {max_results} results)")
                        return "\n".join(results)
        except Exception:
            continue

    if not results:
        return f"(no matches for '{pattern}' in '{path}')"
    return "\n".join(results)


# ─────────────────────────────────────────────────────────────
# CONTEXT & NAVIGATION
# ─────────────────────────────────────────────────────────────

def understand_cwd(max_depth: int = 2) -> str:
    """
    Builds an operational map of the current environment:
    cwd, Python version, platform, selected env variables (whitelist),
    directory structure (up to max_depth levels, excluding noisy folders).
    """
    cwd = Path.cwd()

    # Whitelist: only vars with operational meaning for an agent.
    # Covers Windows, Linux and macOS. Everything else is counted but not shown.
    _useful = {
        # Machine and user identity
        "COMPUTERNAME", "HOSTNAME",                         # Windows / Linux+macOS
        "USERNAME", "USER",                                 # Windows / Linux+macOS
        "USERPROFILE", "HOME",                              # Windows / Linux+macOS
        "HOMEPATH", "HOMEDRIVE",                            # Windows only
        "LOGONSERVER", "SESSIONNAME",                       # Windows only
        # Operating system
        "OS", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",        # Windows only
        # Temporary directory
        "TEMP", "TMP", "TMPDIR",                            # Win / Linux+macOS
        # Shell and terminal
        "SHELL", "TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM",
        # Locale
        "LANG", "LC_ALL", "LC_CTYPE",
        # Hardware
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",   # Windows
        # Python environments
        "CONDA_DEFAULT_ENV", "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT",
        # Miscellaneous
        "PWD",                                              # Linux+macOS
    }
    shown_env  = {k: v for k, v in os.environ.items() if k in _useful}
    hidden_cnt = len(os.environ) - len(shown_env)

    # Folders to hide entirely from the tree
    _hide = {"venv", ".venv", "__pycache__", ".git",
             "node_modules", "dist", "build", ".tox", ".mypy_cache",
             ".pytest_cache", "*.egg-info"}

    def _tree(p: Path, depth: int, prefix: str = "") -> list[str]:
        if depth == 0:
            return []
        rows = []
        try:
            children = sorted(p.iterdir())
        except PermissionError:
            return [f"{prefix}[permission denied]"]
        visible = [
            c for c in children
            if c.name not in _hide
            and not c.name.endswith(".egg-info")
            and (not c.name.startswith(".") or c.name == ".env")
        ]
        for child in visible[:30]:
            connector = "dir" if child.is_dir() else "   "
            rows.append(f"{prefix}[{connector}] {child.name}")
            if child.is_dir() and depth > 1:
                rows.extend(_tree(child, depth - 1, prefix + "    "))
        if len(visible) > 30:
            rows.append(f"{prefix}... ({len(visible) - 30} more)")
        return rows

    tree_lines = _tree(cwd, max_depth)
    env_lines  = [f"  {k}={v}" for k, v in sorted(shown_env.items())]

    return "\n".join([
        f"cwd      : {cwd}",
        f"python   : {sys.version.split()[0]}  ({sys.executable})",
        f"platform : {sys.platform}",
        "",
        "directory structure:",
        *tree_lines,
        "",
        f"environment ({len(shown_env)} shown, {hidden_cnt} hidden):",
        *env_lines,
    ])


# ─────────────────────────────────────────────────────────────
# EXECUTION
# ─────────────────────────────────────────────────────────────

def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and ALL its descendants. Survives shell=True on Windows
    (where Popen.kill() only kills cmd.exe, leaving the actual child orphaned)
    and POSIX (where the shell may have spawned a process group)."""
    if proc.poll() is not None:
        return  # already exited
    pid = proc.pid
    try:
        if sys.platform == "win32":
            # /T = tree (all descendants), /F = force
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:
        # Last-resort fallback — kills only the direct child
        try: proc.kill()
        except Exception: pass


def execute_command(command: str, cwd: str = "", timeout: int = 60,
                    capture_stderr: bool = True,
                    max_output_chars: int = 10_000,
                    stop_event=None) -> str:
    """
    Execute a shell command. Captures stdout, stderr, returncode.
    Returns a formatted string with all three values.
    cwd             : working directory (default: current cwd)
    max_output_chars: truncates stdout and stderr if too long (default 10k chars)

    Timeout is enforced by killing the ENTIRE process tree (not just the shell)
    so a hanging child — e.g. a pygame loop, an `input()` call, a server — cannot
    survive past `timeout` seconds.

    CROSS-PLATFORM NOTE: shell=True uses cmd.exe on Windows and /bin/sh on Linux.
    Commands must be written for the target platform.
    Portable commands: echo, cd, python, pip, git.
    Not portable: ls (Linux) vs dir (Windows), cat vs type, etc.
    """
    work_dir = cwd if cwd else None

    # Spawn in a new process group / job so we can kill the whole tree.
    popen_kwargs: dict = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=work_dir,
    )
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True  # detaches the shell + children

    try:
        proc = subprocess.Popen(command, **popen_kwargs)
    except Exception as e:
        return f"ERROR: {e}"

    timed_out = False
    stopped   = False
    out, err  = "", ""
    try:
        if stop_event is not None:
            # Poll communicate() in slices so we can react to stop_event mid-run
            elapsed = 0.0
            poll    = 0.25
            while True:
                if stop_event.is_set():
                    stopped = True
                    _kill_process_tree(proc)
                    try: out, err = proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired: out, err = "", ""
                    break
                try:
                    out, err = proc.communicate(timeout=poll)
                    break
                except subprocess.TimeoutExpired:
                    elapsed += poll
                    if elapsed >= timeout:
                        timed_out = True
                        _kill_process_tree(proc)
                        try: out, err = proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired: out, err = "", ""
                        break
        else:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_tree(proc)
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    _kill_process_tree(proc)
                    try: out, err = proc.communicate(timeout=2)
                    except subprocess.TimeoutExpired: out, err = "", ""
    except Exception as e:
        _kill_process_tree(proc)
        return f"ERROR: {e}"

    out = (out or "").strip()
    err = (err or "").strip()

    if len(out) > max_output_chars:
        out = out[:max_output_chars] + f"\n... (truncated at {max_output_chars} chars)"
    if len(err) > max_output_chars:
        err = err[:max_output_chars] + f"\n... (truncated at {max_output_chars} chars)"

    if stopped:
        parts = ["INTERRUPTED: command killed by stop signal — process tree was terminated."]
        if out: parts.append(f"stdout (partial):\n{out}")
        if err and capture_stderr: parts.append(f"stderr (partial):\n{err}")
        return "\n".join(parts)

    if timed_out:
        parts = [
            f"ERROR: command timed out after {timeout}s — process tree was killed.",
            "Possible causes: the script is waiting for user input (input()), "
            "an infinite loop, a GUI window (pygame/tkinter), or a long-running operation. "
            "If the script uses input(), remove it and use hardcoded test values instead.",
        ]
        if out: parts.append(f"stdout (partial):\n{out}")
        if err and capture_stderr: parts.append(f"stderr (partial):\n{err}")
        return "\n".join(parts)

    rc = proc.returncode
    parts = [f"returncode: {rc}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err and capture_stderr:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────
# PLANNING
# ─────────────────────────────────────────────────────────────

def todo_create(tasks, output_path: str = "todo.json") -> str:
    """
    Write a structured task list as JSON.
    tasks : list of dicts, JSON string, or plain text (one task per line).
    Schema for each task:
        id          : int
        description : str
        priority    : "high" | "medium" | "low"
        dependencies: list[int]   (ids of prerequisite tasks)
        assignee    : str         (skill name or sub-agent)
        status      : "pending"   (default)

    Returns "OK: N tasks written to <path>" or an error message.
    """
    # ── Step 1: normalise to a raw list ──────────────────────────────────────
    # The agent may pass tasks as a Python list (already parsed from JSON args),
    # as a JSON string, or as plain newline-separated text.
    if isinstance(tasks, list):
        raw = tasks
    elif isinstance(tasks, dict):
        raw = tasks.get("tasks", [tasks])
    elif isinstance(tasks, str):
        try:
            parsed = json.loads(tasks)
            if isinstance(parsed, list):
                raw = parsed
            elif isinstance(parsed, dict) and "tasks" in parsed:
                raw = parsed["tasks"]
            else:
                raw = [parsed]
        except json.JSONDecodeError:
            # Plain text: one task per line
            lines = [l.strip() for l in tasks.strip().splitlines() if l.strip()]
            raw = lines  # will be handled as strings in step 2
    else:
        return f"ERROR: unexpected tasks type: {type(tasks).__name__}"

    # ── Step 2: normalise each item to a dict ────────────────────────────────
    normalized = []
    for i, t in enumerate(raw):
        if isinstance(t, str):
            # Plain string → use as description
            t = {"description": t}
        elif not isinstance(t, dict):
            t = {"description": str(t)}
        normalized.append({
            "id":           t.get("id", i + 1),
            "description":  t.get("description", str(t)),
            "priority":     t.get("priority", "medium"),
            "dependencies": t.get("dependencies", []),
            "assignee":     t.get("assignee", ""),
            "status":       t.get("status", "pending"),
        })

    if not normalized:
        return "ERROR: no tasks provided"

    payload = {"tasks": normalized, "created_at": _now()}
    try:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"OK: {len(normalized)} tasks written to {output_path}"
    except Exception as e:
        return f"ERROR writing todo: {e}"


# ─────────────────────────────────────────────────────────────
# SESSION BROADCAST
# ─────────────────────────────────────────────────────────────

# Optional handler for Pattern B (FastAPI + WebSocket).
# A FastAPI server registers it with register_broadcast_handler().
# Without a handler, the skill works as a logging stub.
_BROADCAST_HANDLER: Optional[Callable] = None


def register_broadcast_handler(fn: Callable) -> None:
    """
    Register a real broadcast function.
    Expected signature: fn(channel: str, event_type: str, payload: str) -> None
    Call from the FastAPI server at startup:
        from skills.d import register_broadcast_handler
        register_broadcast_handler(my_ws_broadcast)
    """
    global _BROADCAST_HANDLER
    _BROADCAST_HANDLER = fn


def session_broadcast(event_type: str, payload: str = "",
                      channel: str = "default") -> str:
    """
    Publish an event on the session channel (WebSocket or log).
    In Pattern B: the handler is registered by the FastAPI server.
    In standalone baseline: falls back to stdout (stub).
    Returns a confirmation string.
    """
    if _BROADCAST_HANDLER is not None:
        try:
            _BROADCAST_HANDLER(channel, event_type, payload)
            return f"broadcast OK: {channel}/{event_type}"
        except Exception as e:
            return f"broadcast ERROR: {e}"
    # Stub fallback
    msg = f"[session_broadcast] {channel}/{event_type}"
    if payload:
        msg += f": {payload[:120]}"
    print(msg)
    return f"broadcast stub: {channel}/{event_type}"


# ─────────────────────────────────────────────────────────────
# QUALITY & OBSERVABILITY
# ─────────────────────────────────────────────────────────────

def schema_validate(data: str, required_fields: str = "",
                    field_types: str = "") -> str:
    """
    Verify that data is valid JSON and matches the expected structure.
    required_fields : mandatory fields separated by comma (e.g. "id,name,status")
    field_types     : JSON string {"field": "str|int|float|bool|list|dict"}
                      e.g. '{"id":"int","name":"str"}'
    Returns "VALID" or "INVALID: <reason>".
    """
    _type_map = {"str": str, "int": int, "float": float,
                 "bool": bool, "list": list, "dict": dict}

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return f"INVALID: not valid JSON — {e}"

    errors: list[str] = []

    if required_fields:
        for field in [f.strip() for f in required_fields.split(",") if f.strip()]:
            if field not in parsed:
                errors.append(f"missing required field: '{field}'")

    if field_types:
        try:
            types = json.loads(field_types)
            for field, expected in types.items():
                cls = _type_map.get(expected)
                if cls and field in parsed:
                    if not isinstance(parsed[field], cls):
                        actual = type(parsed[field]).__name__
                        errors.append(f"field '{field}': expected {expected}, got {actual}")
        except json.JSONDecodeError as e:
            errors.append(f"invalid field_types JSON: {e}")

    if errors:
        return "INVALID:\n" + "\n".join(f"  - {e}" for e in errors)
    return "VALID"


def log_event(message: str, severity: str = "INFO",
              agent_id: str = "baseline", context: str = "",
              log_path: str = "agent.log") -> str:
    """
    Write a structured log entry (JSON Lines) to a file.
    severity : DEBUG | INFO | WARN | ERROR
    context  : optional JSON string with additional data
    Returns the entry as a string.
    """
    entry: dict[str, Any] = {
        "ts":       _now(),
        "severity": severity.upper(),
        "agent":    agent_id,
        "message":  message,
    }
    if context:
        try:
            entry["context"] = json.loads(context)
        except json.JSONDecodeError:
            entry["context"] = context

    line = json.dumps(entry, ensure_ascii=False)
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        return f"LOG WRITE ERROR: {e} | entry: {line}"
    return line


# ─────────────────────────────────────────────────────────────
# INFORMATION RETRIEVAL
# ─────────────────────────────────────────────────────────────

def web_fetch(url: str, timeout: int = 30,
              max_chars: int = 50_000) -> str:
    """
    HTTP GET a URL. Returns the raw content (text).
    max_chars: truncates the body if too long (default 50k chars).
    """
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "homo-agens/agent-baseline"},
        )
        resp.raise_for_status()
        body = resp.text
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n... (truncated at {max_chars} chars)"
        return body
    except requests.HTTPError as e:
        return f"HTTP ERROR {e.response.status_code}: {e}"
    except requests.ConnectionError as e:
        return f"CONNECTION ERROR: {e}"
    except requests.Timeout:
        return f"TIMEOUT after {timeout}s: {url}"
    except Exception as e:
        return f"ERROR: {e}"


# ─────────────────────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────────────────────

SKILLS: dict[str, Callable] = {
    # Filesystem
    "read_file":         read_file,
    "write_file":        write_file,
    "list_dir":          list_dir,
    "glob_match":        glob_match,
    "grep_search":       grep_search,
    # Context
    "understand_cwd":    understand_cwd,
    # Execution
    "execute_command":   execute_command,
    # Planning
    "todo_create":       todo_create,
    # Session
    "session_broadcast": session_broadcast,
    # Quality
    "schema_validate":   schema_validate,
    "log_event":         log_event,
    # Retrieval
    "web_fetch":         web_fetch,
}
