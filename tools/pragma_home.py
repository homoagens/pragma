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
{"action": "projects" | "open" | "new" | "backups" | "delete"
          | "configure" | "exit", "arg": "..."}
and the process ends.

MEMORY AT WORK. A consolidation runs in its own process and outlives the
conversation that started it, so this screen says when one is going: a `memory`
line naming the project and the faculty in flight, the detail being /jobs
inside the project. While it lasts, /exit and ctrl+D say so instead of leaving;
a second ctrl+D straight after goes anyway. The work is never interrupted - the
worker is not this process - so this is a reminder, not a lock.

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
import time
from pathlib import Path

REGISTRY = Path.home() / ".pragma" / "registry.json"
GREY, RESET = "\033[38;5;242m", "\033[0m"


def _encodes(text: str) -> bool:
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except Exception:
        return False


SEP = " · " if _encodes("·") else " - "

# Order is the order on the page: open before new, because over the life of a
# project it is opened every day and created once.
#
# /open AND /new ARE COMMANDS, not aliases of /projects. The most common thing
# anyone does on this screen is go back into yesterday's project, and it took
# three steps: /projects, then "open", then the name. Now the page lists the
# recent projects and /open takes the name, with tab completing it.
COMMANDS = {
    "/open":      "go into a project - /open <name>, tab completes it",
    "/new":       "start a project",
    "/projects":  "",                     # the actions fill the blurb in
    "/jobs":      "what the memory is writing in the background",
    "/configure": "the model server Pragma talks to",
    "/clear":     "clear the screen",
    "/help":      "this list",
    "/exit":      "leave",
}

# What /projects takes. These are the things that are done TO a project rather
# than inside one, which is why they live here and not in a conversation: from
# inside a project, starting another one or deleting a third was a door in the
# wrong room. Bare /projects opens the page and you pick there.
PROJECT_ACTIONS = {
    "open":    "open a project and start talking; /projects open <name> goes straight in",
    "new":     "start a project",
    "backups": "snapshot a project's memory, or put one back",
    "delete":  "remove a project, and the memory it keeps",
}

# Old names and short ones, offered by nothing: fingers that learned them keep
# working, the page stays short.
ALIASES = {"/q": "/exit", "/quit": "/exit", "/?": "/help", "/project": "/projects",
           "/o": "/open", "/n": "/new"}
ALIASES.update({f"/{action}": f"/projects {action}" for action in PROJECT_ACTIONS
                if f"/{action}" not in COMMANDS})
ROOT = Path(__file__).resolve().parent.parent


def rows() -> list[tuple[str, str]]:
    """The command rows for the home page, as the state makes them.

    With nothing registered there is nothing to open, back up or delete, and
    no memory that could be writing: a page listing them would be four doors
    onto an empty room. /new, and the endpoint you will need anyway.
    """
    if not registry_entries():
        return [("/new", "start your first project"),
                ("/configure", COMMANDS["/configure"]),
                ("/help", COMMANDS["/help"]),
                ("/exit", COMMANDS["/exit"])]
    shown = ("/open", "/new", "/projects", "/jobs", "/configure", "/exit")
    return [(name, "backups" + SEP + "delete" + SEP + "the full list"
             if name == "/projects" else COMMANDS[name]) for name in shown]


# How many projects the page lists before saying how many more there are.
RECENT = 5


def _when(stamp: str) -> str:
    """"2026-09-28T10:00:00Z" -> "2 days ago", as the page says it."""
    from datetime import datetime, timezone
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return "never opened"
    days = (datetime.now(timezone.utc).date() - then.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    return then.strftime("%d %b %Y")


def _home_short(path: str) -> str:
    """A path with the home folder written as ~, the way a person reads it."""
    home = str(Path.home())
    p = str(path or "")
    return "~" + p[len(home):] if home and p.startswith(home) else p


def page(notice: str = "") -> None:
    """The body of the home page, under the mark: the projects, the commands.

    Drawn here for BOTH launchers. The PowerShell one and the Python one each
    drew their own copy, with a comment asking whoever changed one to change
    the other - which is how the two came to disagree about what the page
    said. Now the page is one function and the launchers draw the mark.
    """
    a = accent()
    grey, reset = (GREY, RESET) if a else ("", "")
    entries = registry_entries()
    print()
    if not entries:
        print(f"  {grey}No projects yet.{reset}")
    else:
        entries.sort(key=lambda e: str(e.get("last_opened") or ""), reverse=True)
        listed = entries[:RECENT]
        width = min(24, max(len(str(e["name"])) for e in listed))
        wheres = [_home_short(str(e.get("workspace") or "")) for e in listed]
        whens = [_when(str(e.get("last_opened") or "")) for e in listed]
        # The folder column is as wide as the longest folder, not as wide as
        # the window: "today" belongs next to its path, not at the far edge.
        room = max(10, _columns() - 4 - width - 2 - max(len(w) for w in whens) - 3)
        span = min(room, max(len(w) for w in wheres))
        for e, where, when in zip(listed, wheres, whens):
            if len(where) > span:
                where = "…" + where[-(span - 1):]
            print(f"  {a}{str(e['name']):<{width}}{reset}  {grey}{where:<{span}}   {when}{reset}")
        more = len(entries) - RECENT
        if more > 0:
            print(f"  {grey}and {more} more - /projects lists them all{reset}")
    print()
    for command, blurb in rows():
        print(f"  {a}{command:<12}{reset}{grey}{blurb}{reset}")
    if notice:
        print()
        print(f"  \033[33m{notice}{reset}" if a else f"  {notice}")


def _columns() -> int:
    try:
        import shutil
        return max(40, shutil.get_terminal_size((80, 24)).columns)
    except Exception:
        return 80


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


def registry_entries() -> list[dict]:
    """The registered projects, or nothing at all when the file cannot be read."""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [e for e in data if isinstance(e, dict) and e.get("name")]


def project_names() -> list[str]:
    """Registered project names, for completing /open <name>."""
    return [str(e["name"]) for e in registry_entries()]


def memory_jobs() -> list[tuple[str, str]]:
    """(project, what it is doing) for every consolidation in flight, any project.

    The work runs in its own process and outlives the conversation that started
    it, so from here - with no project open - it is invisible: the screen that
    looks idlest is exactly the one where an episode may still be being
    written. Each job's last log line names the faculty at work.
    """
    os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")
    sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]
    try:
        import pragma_jobs as jobs
    except Exception:
        return []
    out = []
    for entry in registry_entries():
        store = str(entry.get("memory") or "").strip()
        if not store:
            continue
        try:
            found = jobs.listing(Path(store), limit=8)
        except Exception:
            continue
        for job in found:
            if job.get("status") not in ("pending", "running"):
                continue
            out.append((str(entry["name"]), jobs.step_of(job)[:60]))
    return out


def show_jobs() -> None:
    """The memory's background work in every project: followed while it runs,
    listed when it failed, one line when there is nothing.

    The same view the conversation has, from the screen where you actually are
    after leaving a project - which is when a consolidation is running.
    """
    os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")
    sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]
    try:
        import pragma_jobs as jobs
    except Exception as e:
        print(f"  jobs unavailable - {type(e).__name__}: {e}")
        return
    found: list[tuple[str, dict]] = []
    for entry in registry_entries():
        store = str(entry.get("memory") or "").strip()
        if not store:
            continue
        try:
            for job in jobs.listing(Path(store), limit=6):
                found.append((str(entry["name"]), job))
        except Exception:
            continue
    print()
    if not found:
        jobs.show_idle(everywhere=True)
        print()
        return
    live = [(p, j) for p, j in found if j.get("status") in ("pending", "running")]
    failed = [(p, j) for p, j in found if j.get("status") not in ("pending", "running")]
    if live:
        project, job = live[0]
        jobs.header(project, job.get("note") or "a session",
                    also=", ".join(p for p, _ in live[1:]))
        ended = "left"
        try:
            ended = jobs.watch(Path(job["_path"]), job)
        except KeyboardInterrupt:
            print()
            print("  still working - it carries on without you.")
        print()
        # It ended while being watched: what it said stays where it is until
        # it is dismissed. The page behind is about to be drawn again - its
        # own "memory is writing" line is stale now - and that used to happen
        # at once, taking the lines being read with it.
        if ended != "left" and not failed:
            jobs.hold("ctrl+D to go back")
            print()
    if failed:
        jobs.show_failed(failed)
        print()


def memory_line(jobs_running: list[tuple[str, str]], grey: str, reset: str) -> None:
    for project, step in jobs_running:
        busy = "\033[33m" if grey else ""
        print(f"  {grey}{'memory':<12}{reset}{busy}{project} - writing{reset}"
              f"  {grey}{step}{reset}")
    if jobs_running:
        print(f"  {grey}{'':<12}/jobs to watch it{reset}")
        print()


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
            offered = {c: b or " . ".join(PROJECT_ACTIONS) for c, b in COMMANDS.items()}
            offered.update({c: str(s.get("blurb") or "") for c, s in (extra or {}).items()})
            if " " not in text:
                for name, blurb in offered.items():
                    if name.startswith(text.lower()):
                        yield Completion(name, start_position=-len(text),
                                         display=name, display_meta=blurb)
                return
            head, typed = text.split(" ", 1)
            head = head.lower()
            if head == "/projects" and " " not in typed.strip():
                for action, blurb in PROJECT_ACTIONS.items():
                    if action.startswith(typed.strip().lower()):
                        yield Completion(action, start_position=-len(typed),
                                         display=action, display_meta=blurb)
                return
            wants_projects = head in ("/open", "/projects open") or (
                (extra or {}).get(head, {}).get("complete") == "projects")
            if head == "/projects" and typed.strip().lower().startswith("open "):
                wants_projects, typed = True, typed.strip()[5:]
            if wants_projects and " " not in typed.strip():
                for name in project_names():
                    if name.lower().startswith(typed.strip().lower()):
                        yield Completion(name, start_position=-len(typed))

    # The menu's reserved space is kept off the bottom of the screen whether a
    # menu is showing or not, so on a short window it is six lines of page
    # pushed off the top. Four is still two commands and their blurbs, which
    # is what the completion is for here.
    return PromptSession(completer=HomeCompleter(), complete_while_typing=True,
                         reserve_space_for_menu=4)


def read_line(session) -> str:
    """The line, under the same mark the menus and the conversation use."""
    from pragma_menu import MARK
    a = accent()
    if session is None:
        return input(f"  {MARK} ")
    from prompt_toolkit.formatted_text import ANSI
    return session.prompt(
        ANSI(f"  {a}{MARK}{RESET if a else ''} "),
        placeholder=ANSI(f"{GREY}a project's name, or /help{SEP}ctrl+D to exit{RESET}"))


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

    # What is served first, where it is last: the model is what someone came
    # to check, the address is what they check when it is wrong.
    def text(ep):
        p = found[ep.base_url]
        where = endpoints.short_url(ep.base_url)
        if p.get("up"):
            return f"{endpoints.status_text(p)}{SEP}{where}"
        return f"{where}{SEP}{endpoints.status_text(p)}{SEP}/configure"

    if len({ep.base_url for ep in roles.values()}) == 1:
        ep = roles["agent"]
        return [("endpoint", text(ep), found[ep.base_url].get("up", False))]
    return [(role, f"{ep.name} · {text(ep)}", found[ep.base_url].get("up", False))
            for role, ep in roles.items()]


def embedding_line(found: dict | None) -> tuple[str, str]:
    """(text, colour) for the line under the endpoint that says whether the
    memory is searched by meaning, and by what.

    `found` is embed.probe(): None when no embedding server is named. The same
    order as the endpoint's line - what is served, then where - and the same
    two colours, so that the two servers a memory can depend on are read the
    same way. With none named the line is still there, quietly: it is a thing
    this machine could have and does not.
    """
    sys.path[:0] = [str(ROOT), str(ROOT / "core")]
    import endpoints
    if found is None:
        return f"none - the memory is searched by words{SEP}/configure", GREY
    where = endpoints.short_url(found["url"])
    if found.get("up"):
        served = endpoints.model_name(found.get("model") or "") or "answering"
        return f"{served}{SEP}{where}", "\033[32m"
    return f"{where}{SEP}not answering - the memory is searched by words{SEP}/configure", "\033[33m"


def show_help(extra: dict | None = None) -> None:
    a = accent()
    r = RESET if a else ""
    print()
    for name, blurb in COMMANDS.items():
        print(f"    {a}{name:<12}{r}{blurb or ''}")
        if name == "/projects":
            for action, what in PROJECT_ACTIONS.items():
                print(f"      {a}{action:<10}{r}{what}")
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
    ap.add_argument("--out", help="where to write the chosen action")
    # The launcher leaves for good from two places, and only one of them is
    # this prompt. --jobs answers the other one: what the memory is writing,
    # as JSON, without a page or a prompt.
    ap.add_argument("--jobs", action="store_true",
                    help="print the memory work in flight as JSON and stop")
    # The body of the page - the projects and the commands - drawn here for
    # both launchers, which draw only the mark above it. See page().
    ap.add_argument("--page", action="store_true",
                    help="draw the projects and the commands before the prompt")
    ap.add_argument("--notice", default="",
                    help="one line to say under the commands (a name not found, ...)")
    args = ap.parse_args()
    if args.jobs:
        print(json.dumps([{"project": p, "step": s} for p, s in memory_jobs()]))
        return 0
    if not args.out:
        ap.error("--out is required")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def choose(action: str, arg: str = "") -> int:
        Path(args.out).write_text(json.dumps({"action": action, "arg": arg}),
                                  encoding="utf-8")
        return 0

    if args.page:
        page(args.notice)
    # The embedding server is asked while the endpoints are, not after them:
    # one that is down must not add its wait to theirs.
    os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")
    sys.path[:0] = [str(ROOT), str(ROOT / "core")]
    embedding: dict = {}

    def ask_embedding() -> None:
        try:
            import embed
            embedding["found"] = embed.probe(2.5)
            embedding["asked"] = True
        except Exception:
            pass

    import threading
    asking = threading.Thread(target=ask_embedding, daemon=True)
    asking.start()
    try:
        lines = endpoint_lines()
    except Exception as e:
        lines = [("endpoint", f"unknown - {type(e).__name__}", False)]
    asking.join(3.5)
    a = accent()
    grey = GREY if a else ""
    reset = RESET if a else ""
    # A line of its own above the endpoint, and the endpoint wrapped under
    # itself: it used to sit flush under /exit, reading as a sixth command,
    # and to run past the window's edge onto the next line at column 0.
    print()
    from pragma_menu import row
    for label, status, up in lines:
        row(label, status, "\033[32m" if up else "\033[33m")
    # Under the endpoint, whether the memory is searched by meaning. That
    # there is NO embedding server is said only on a machine whose model
    # answers: on a first run the one line to read is the endpoint's, and a
    # second one about something optional would be read instead of it.
    if embedding.get("asked") and (embedding.get("found") is not None
                                   or any(up for _label, _status, up in lines)):
        row("embedding", *embedding_line(embedding.get("found")))
    print()

    # What the page says the memory is doing is a photograph taken as it was
    # drawn. /jobs uses it to know whether the page has gone stale.
    shown_jobs: list = []
    try:
        shown_jobs = memory_jobs()
        memory_line(shown_jobs, grey, reset)
    except Exception:
        pass

    extra, problems = plugin_commands()
    if extra:
        print(f"  {grey}{'plugins':<12}{reset}{' · '.join(extra)}  {grey}/help says what they do{reset}")
        print()
    for problem in problems:
        print(f"  {problem}")
    if problems:
        print()
    session = make_session(extra)
    # Leaving while a faculty is mid-sentence loses nothing - the worker is its
    # own process and carries on - but the operator who quits without knowing
    # the memory is still being written has no way to learn it happened. So the
    # way out is held once, and a second ctrl+D straight after it goes anyway:
    # a reminder, not a lock.
    insisted = 0.0

    def held_back() -> bool:
        nonlocal insisted
        busy = []
        try:
            busy = memory_jobs()
        except Exception:
            return False
        if not busy:
            return False
        print()
        for project, step in busy:
            print(f"  the memory is still writing - {project}  {GREY if a else ''}{step}{reset}")
        print("  it finishes on its own. /exit or ctrl+D again to leave anyway.")
        print()
        insisted = time.time()
        return True

    def again() -> bool:
        """Was the way out asked for a moment ago, and held back? Then go."""
        return time.time() - insisted <= 10.0

    while True:
        try:
            # A byte-order mark is what a pipe from PowerShell puts in front of
            # the first line; typed or piped, the command is the same.
            line = read_line(session).lstrip("﻿").strip()
        except (EOFError, KeyboardInterrupt):
            if again() or not held_back():
                return choose("exit")
            continue
        except Exception:
            # A console prompt_toolkit cannot drive is not a reason to lose the
            # home screen: the plain prompt still takes the same commands.
            if session is None:
                raise
            session = None
            continue
        if not line:
            continue
        # A project's name, typed as it is, opens it: the page lists them, and
        # the name is the thing someone reads there and types back.
        if not line.startswith("/"):
            named = next((n for n in project_names() if n.lower() == line.lower()), "")
            if named:
                return choose("open", named)
        head, _, rest = line.partition(" ")
        cmd = head.lower() if head.startswith("/") else "/" + head.lower()
        if cmd in ALIASES:                  # "/delete" -> "/projects delete"
            cmd, _, more = ALIASES[cmd].partition(" ")
            rest = (more + " " + rest).strip() if more else rest
        if cmd == "/help":
            show_help(extra)
        elif cmd == "/jobs":
            show_jobs()
            # The page said the memory was writing when it was drawn. If that
            # has finished, the line is now wrong, and it stays on the screen
            # being wrong - so the page is drawn again, saying so.
            try:
                if shown_jobs and not memory_jobs():
                    return choose("clear", "the memory has finished writing")
            except Exception:
                pass
        elif cmd == "/exit":
            # Typed, not a keystroke: it says what is happening and stays -
            # and a second /exit goes, as a second ctrl+D does.
            if again() or not held_back():
                return choose("exit")
        elif cmd == "/projects":
            action, _, name = rest.strip().partition(" ")
            if not action:
                return choose("projects")
            if action.lower() not in PROJECT_ACTIONS:
                print(f"  /projects takes one of: {', '.join(PROJECT_ACTIONS)}")
                print()
                continue
            return choose(action.lower(), name.strip())
        elif cmd in COMMANDS:
            return choose(cmd[1:], rest.strip())
        elif cmd in extra:
            code = run_plugin(extra[cmd], rest.strip())
            if code:
                print(f"  ({cmd} ended with code {code})")
                print()
        elif not line.startswith("/"):
            # A bare word is read as a project's name, so that is what the
            # answer is about - "bad is not a command", cut at the first
            # space, answered a question nobody had asked.
            names = project_names()
            print(f"  no project is called '{line}'."
                  + (" /open lists them, /new starts one." if names else " /new starts one."))
            print()
        else:
            print(f"  {head} is not a command here. /help lists them.")
            print()


if __name__ == "__main__":
    sys.exit(main())
