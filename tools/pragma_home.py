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
"""

import argparse
import json
import os
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


def make_session():
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
            if " " not in text:
                for name, blurb in COMMANDS.items():
                    if name.startswith(text.lower()):
                        yield Completion(name, start_position=-len(text),
                                         display=name, display_meta=blurb)
            elif text.lower().startswith("/open "):
                typed = text[len("/open "):]
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


def endpoint_line() -> str:
    """One line on the endpoint: connected and what it serves, or not connected.

    A bare connection test first, so a missing server costs a second and the
    prompt appears anyway; only a server that answers is asked what it serves.
    config is imported with its own import-time probe switched off, because
    that probe is exactly the wait this avoids.
    """
    os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")
    root = Path(__file__).resolve().parent.parent
    sys.path[:0] = [str(root), str(root / "core")]
    import urllib.request
    import config
    url = (config.LLM_BASE_URL or "http://127.0.0.1:8080/v1").rstrip("/")
    if not config.endpoint_reachable(url):
        return f"not connected - {url} · /configure to set it up"

    def get(path):
        req = urllib.request.Request(path)
        if config.LLM_API_KEY:
            req.add_header("Authorization", f"Bearer {config.LLM_API_KEY}")
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    parts = [url]
    try:
        data = get(url + "/models").get("data") or []
        model = str(data[0].get("id", "")) if data else ""
        model = model.replace("\\", "/").split("/")[-1]
        for ext in (".gguf", ".bin"):
            if model.lower().endswith(ext):
                model = model[:-len(ext)]
        if model:
            parts.append(model)
    except Exception:
        return f"{url} answers, but not as an OpenAI-compatible endpoint · /configure"
    try:
        props = get((url[:-3] if url.endswith("/v1") else url).rstrip("/") + "/props")
        n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        slots = props.get("total_slots")
        if n_ctx:
            parts.append(f"{slots} slot(s) x {n_ctx} tokens" if slots else f"{n_ctx} tokens")
    except Exception:
        pass                            # not llama.cpp: /props is optional
    return "connected - " + " · ".join(parts)


def show_help() -> None:
    a = accent()
    r = RESET if a else ""
    print()
    for name, blurb in COMMANDS.items():
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
        status = endpoint_line()
    except Exception as e:
        status = f"unknown - {type(e).__name__}"
    a = accent()
    grey = GREY if a else ""
    reset = RESET if a else ""
    colour = "\033[32m" if status.startswith("connected") else "\033[33m"
    print(f"  {grey}endpoint{reset}    {colour if a else ''}{status}{reset}")
    print()

    session = make_session()
    while True:
        try:
            line = read_line(session).strip()
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
            show_help()
        elif cmd in COMMANDS:
            return choose(cmd[1:], rest.strip())
        else:
            print(f"  {head} is not a command here. /help lists them.")
            print()


if __name__ == "__main__":
    sys.exit(main())
