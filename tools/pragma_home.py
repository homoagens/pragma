#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""The launcher's home prompt: /open, /new, /configure, /help, /exit.

The screen before any project is open speaks the same slash commands as the
conversation, so it gets the same prompt: commands completed as they are
typed, and a grey hint on the empty line. PowerShell reading a line has
neither, which is why the line is read here.

    venv\Scripts\python.exe tools\pragma_home.py --out <file>

The launcher draws the page and runs this for the line. /help and mistakes
are answered here, under the page, and the prompt asks again. Anything the
launcher has to do is written to --out as
{"action": "open" | "new" | "configure" | "exit", "arg": "..."}
and the process ends.

PLUGINS. A plugin adds commands to this prompt without Pragma knowing what it
is: ~/.pragma/plugins/<name>/plugin.json (PRAGMA_PLUGINS names another folder)
declares them.

    {"name": "example",
     "commands": {"/hello": {"blurb": "say hello - /hello <project>",
                             "run": ["{python}", "-m", "example.cli", "hello"],
                             "cwd": "C:/path/to/example",
                             "complete": "projects"}}}

The command runs here, in this window, with what was typed after it appended
as arguments, and the prompt comes back when it ends. {python} is Pragma's own
interpreter, {plugin} the plugin's folder, {pragma} the repository;
"complete": "projects" completes project names after the command. A plugin
cannot replace a built-in command, and one that cannot be read is skipped with
a line saying why. With no plugins, nothing on this screen changes.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REGISTRY = Path.home() / ".pragma" / "registry.json"
GREY, RESET = "\033[38;5;242m", "\033[0m"

# Order is the order on the page: open before new, because over the life of a
# project it is opened every day and created once.
COMMANDS = {
    "/open":      "open a project; /open <name> goes straight in",
    "/new":       "start a project",
    "/configure": "set up the endpoint",
    "/help":      "this list",
    "/exit":      "leave",
}
ALIASES = {"/o": "/open", "/n": "/new", "/q": "/exit", "/quit": "/exit", "/?": "/help"}
ROOT = Path(__file__).resolve().parent.parent


def plugins_dir() -> Path:
    raw = os.environ.get("PRAGMA_PLUGINS", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".pragma" / "plugins"


def plugin_commands() -> tuple[dict, list[str]]:
    """({command: spec}, [problems]) from every plugin.json, in folder order."""
    found: dict[str, dict] = {}
    problems: list[str] = []
    folder = plugins_dir()
    if not folder.is_dir():
        return found, problems
    taken = set(COMMANDS) | set(ALIASES)
    for manifest in sorted(folder.glob("*/plugin.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            name = str(data.get("name") or manifest.parent.name)
            commands = data.get("commands") or {}
            if not isinstance(commands, dict):
                raise ValueError('"commands" must be an object')
        except Exception as e:
            problems.append(f"plugin {manifest.parent.name}: cannot be read ({e})")
            continue
        for command, spec in commands.items():
            run = spec.get("run") if isinstance(spec, dict) else None
            if not re.fullmatch(r"/[a-z][a-z0-9-]*", str(command)):
                problems.append(f"plugin {name}: '{command}' is not a command name")
            elif command in taken:
                problems.append(f"plugin {name}: {command} is already taken")
            elif not (isinstance(run, list) and run and all(isinstance(a, str) for a in run)):
                problems.append(f"plugin {name}: {command} has no \"run\" list")
            else:
                taken.add(command)
                found[command] = dict(spec, plugin=name, folder=str(manifest.parent))
    return found, problems


def run_plugin(spec: dict, arg: str) -> int:
    """Run a plugin command in this window; the prompt comes back when it ends."""
    subst = {"{python}": sys.executable, "{plugin}": spec["folder"], "{pragma}": str(ROOT)}

    def fill(token: str) -> str:
        for placeholder, value in subst.items():
            token = token.replace(placeholder, value)
        return token

    argv = [fill(a) for a in spec["run"]] + arg.split()
    cwd = spec.get("cwd") or spec["folder"]
    env = dict(os.environ, PRAGMA_ROOT=str(ROOT), PRAGMA_PYTHON=sys.executable)
    print()
    try:
        return subprocess.run(argv, cwd=cwd, env=env).returncode
    except Exception as e:
        print(f"  the plugin could not start: {type(e).__name__}: {e}")
        return 1
    finally:
        print()


def accent() -> str:
    """The launcher's accent as an ANSI foreground, as the chat prompt uses it."""
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        raw = "178;132;255"
    return "\033[38;2;" + raw + "m" if sys.stdout.isatty() else ""


def project_names() -> list[str]:
    """Registered project names, for completing /open <name>."""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [str(e["name"]) for e in data if isinstance(e, dict) and e.get("name")]


def make_session(extra: dict | None = None):
    """A prompt with completion, or None to fall back to input()."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
    except Exception:
        return None

    class HomeCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            offered = dict(COMMANDS)
            offered.update({c: str(s.get("blurb") or "") for c, s in (extra or {}).items()})
            if " " not in text:
                for name, blurb in offered.items():
                    if name.startswith(text.lower()):
                        yield Completion(name, start_position=-len(text),
                                         display=name, display_meta=blurb)
                return
            head, typed = text.split(" ", 1)
            wants_projects = head.lower() == "/open" or (
                (extra or {}).get(head.lower(), {}).get("complete") == "projects")
            if wants_projects and " " not in typed:
                for name in project_names():
                    if name.lower().startswith(typed.lower()):
                        yield Completion(name, start_position=-len(typed))

    return PromptSession(completer=HomeCompleter(), complete_while_typing=True,
                         reserve_space_for_menu=6)


def read_line(session) -> str:
    a = accent()
    if session is None:
        return input("  > ")
    from prompt_toolkit.formatted_text import ANSI
    return session.prompt(
        ANSI(f"  {a}>{RESET if a else ''} "),
        placeholder=ANSI(f"{GREY}/help for the commands · ctrl+D to exit{RESET}"))


def endpoint_lines() -> list[tuple[str, str, bool]]:
    """(label, text, up) for the endpoint, or one per role when they differ.

    A bare connection test first, so a missing server costs a second and the
    prompt appears anyway; only a server that answers is asked what it serves.
    config is imported with its own import-time probe switched off, because
    that probe is exactly the wait this avoids.
    """
    os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")
    root = Path(__file__).resolve().parent.parent
    sys.path[:0] = [str(root), str(root / "core")]
    import endpoints
    try:
        roles = endpoints.assignments()
    except endpoints.EndpointError as e:
        return [("endpoints", f"catalogue unusable - {e} · /configure", False)]
    found = endpoints.probe_all(list(roles.values()))

    def text(ep):
        p = found[ep.base_url]
        body = f"{ep.base_url} · {endpoints.status_text(p)}"
        return body if p.get("up") else f"{body} · /configure"

    if len({ep.base_url for ep in roles.values()}) == 1:
        ep = roles["agent"]
        return [("endpoint", text(ep), found[ep.base_url].get("up", False))]
    return [(role, f"{ep.name} · {text(ep)}", found[ep.base_url].get("up", False))
            for role, ep in roles.items()]


def show_help(extra: dict | None = None) -> None:
    a = accent()
    r = RESET if a else ""
    print()
    for name, blurb in COMMANDS.items():
        print(f"    {a}{name:<12}{r}{blurb}")
    by_plugin: dict[str, list] = {}
    for name, spec in (extra or {}).items():
        by_plugin.setdefault(spec["plugin"], []).append((name, spec.get("blurb") or ""))
    for plugin, items in by_plugin.items():
        print()
        print(f"    {GREY if a else ''}from the {plugin} plugin{r}")
        for name, blurb in items:
            print(f"    {a}{name:<12}{r}{blurb}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(prog="pragma_home")
    ap.add_argument("--out", required=True, help="where to write the chosen action")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def choose(action: str, arg: str = "") -> int:
        Path(args.out).write_text(json.dumps({"action": action, "arg": arg}),
                                  encoding="utf-8")
        return 0

    try:
        lines = endpoint_lines()
    except Exception as e:
        lines = [("endpoint", f"unknown - {type(e).__name__}", False)]
    a = accent()
    grey = GREY if a else ""
    reset = RESET if a else ""
    for label, status, up in lines:
        colour = ("\033[32m" if up else "\033[33m") if a else ""
        print(f"  {grey}{label:<12}{reset}{colour}{status}{reset}")
    print()

    extra, problems = plugin_commands()
    if extra:
        print(f"  {grey}{'plugins':<12}{reset}{' · '.join(extra)}  {grey}/help says what they do{reset}")
        print()
    for problem in problems:
        print(f"  {problem}")
    if problems:
        print()
    session = make_session(extra)
    while True:
        try:
            # A byte-order mark is what a pipe from PowerShell puts in front of
            # the first line; typed or piped, the command is the same.
            line = read_line(session).lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            return choose("exit")
        except Exception:
            # A console prompt_toolkit cannot drive is not a reason to lose the
            # home screen: the plain prompt still takes the same commands.
            if session is None:
                raise
            session = None
            continue
        if not line:
            continue
        head, _, rest = line.partition(" ")
        cmd = head.lower() if head.startswith("/") else "/" + head.lower()
        cmd = ALIASES.get(cmd, cmd)
        if cmd == "/help":
            show_help(extra)
        elif cmd in COMMANDS:
            return choose(cmd[1:], rest.strip())
        elif cmd in extra:
            code = run_plugin(extra[cmd], rest.strip())
            if code:
                print(f"  ({cmd} ended with code {code})")
                print()
        else:
            print(f"  {head} is not a command here. /help lists them.")
            print()


if __name__ == "__main__":
    sys.exit(main())
