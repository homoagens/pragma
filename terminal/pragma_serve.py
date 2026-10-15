# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""/serve: projects other programs can talk to, as to a model.

    python terminal/pragma_serve.py             the page, from the home screen
    python terminal/pragma_serve.py --autostart start what is on and not running

A served project is a process of its own, agent/serve.py, listening on an
address and a port of its own: a program that talks to an OpenAI-compatible
endpoint is pointed at it and gets the project - its memory, its workspace,
its tools - instead of a bare model.

THEY OUTLIVE THE WINDOW. A served project keeps running when Pragma is
closed: a program using it should not stop working because a terminal did.
So what is served is a list, ~/.pragma/serve.json, with each project on or
off; the home screen says, every time it is drawn, which are on and whether
they are really running; and the next `pragma` starts again any that is on
and is not - after a reboot, say. Only /serve turns one off.

What a running one is doing it writes itself, in ~/.pragma/serve/<name>.json
(see agent/serve.py), and what it logs goes to ~/.pragma/serve/<name>.log.

THE KEY. Each served project has one, made here. A program on this machine
may send none; from anywhere else it must send this one - an address opened
to the network is refused without it.
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT), str(ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pragma_menu import (GREY, RESET, SEP, accent, ask, confirm, pause, pick,   # noqa: E402
                         say, title)

LIST = Path.home() / ".pragma" / "serve.json"
STATE_DIR = Path.home() / ".pragma" / "serve"
FIRST_PORT = 8300
LOCAL = ("127.0.0.1", "localhost", "::1")


# ── the list ─────────────────────────────────────────────────────────────────

def read_list() -> dict:
    """{project: {"host", "port", "key", "on", "memory"}}, in the order they
    were added. "memory" missing is on."""
    try:
        data = json.loads(LIST.read_text(encoding="utf-8"))
        got = data.get("projects") if isinstance(data, dict) else None
        return {str(k): dict(v) for k, v in (got or {}).items() if isinstance(v, dict)}
    except Exception:
        return {}


def save_list(listed: dict) -> None:
    LIST.parent.mkdir(parents=True, exist_ok=True)
    tmp = LIST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"projects": listed}, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)                  # it holds the keys
    except OSError:
        pass
    tmp.replace(LIST)


def free_port(listed: dict, start: int = FIRST_PORT) -> int:
    """The first port from `start` that no served project has and nothing holds."""
    taken = {int(e.get("port") or 0) for e in listed.values()}
    port = start
    while port < 65535:
        if port not in taken:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    pass
        port += 1
    return start


# ── the processes ────────────────────────────────────────────────────────────

def state_of(name: str) -> dict | None:
    """What a running service says about itself, or None when it is not running."""
    try:
        state = json.loads((STATE_DIR / f"{name}.json").read_text(encoding="utf-8"))
        os.kill(int(state["pid"]), 0)
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _registry_entry(name: str) -> dict | None:
    import pragma_launcher
    return pragma_launcher.by_name(name)


def start(name: str, entry: dict) -> str:
    """Start serving a project. "" when it answers, or why it does not."""
    import pragma_launcher
    project = _registry_entry(name)
    if not project:
        return "there is no such project any more"
    if not Path(str(project.get("workspace") or "")).is_dir():
        return f"its folder is missing: {project.get('workspace')}"
    env = pragma_launcher.environment(project)
    env["PRAGMA_SERVE_KEY"] = str(entry.get("key") or "")
    # A service outlives the run that started it, so it does not take that
    # run's --agent: it serves the project with its memory.
    env.pop("PRAGMA_AGENT", None)
    steps = str((project.get("settings") or {}).get("MaxSteps", "")).strip() or pragma_launcher.DEFAULT_STEPS
    host, port = str(entry.get("host") or "127.0.0.1"), int(entry.get("port") or FIRST_PORT)
    argv = [sys.executable, "-m", "agent.serve", "--host", host, "--port", str(port),
            "--max-steps", steps] + ([] if entry.get("memory", True) else ["--no-memory"])
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = open(STATE_DIR / f"{name}.log", "a", encoding="utf-8")
    log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} started from /serve\n")
    log.flush()
    try:
        proc = subprocess.Popen(argv, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, start_new_session=True)
    except OSError as e:
        return f"it could not start: {e}"
    finally:
        log.close()
    # It is up when it answers. A port already taken, a project that cannot
    # be read: the process ends at once, and the log's last line says why.
    until = time.time() + 15
    while time.time() < until:
        if proc.poll() is not None:
            return f"it stopped at once - {last_line(name)}"
        try:
            with urllib.request.urlopen(f"http://{_reach(host)}:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return ""
        except Exception:
            pass
        time.sleep(0.3)
    return f"it does not answer yet - {STATE_DIR / (name + '.log')} says what it is doing"


def stop(name: str) -> bool:
    """Stop a running service; its conversation goes to the memory. Whether it was running."""
    state = state_of(name)
    if not state:
        return False
    try:
        os.kill(int(state["pid"]), signal.SIGTERM)
    except OSError:
        return False
    until = time.time() + 20
    while time.time() < until and state_of(name):
        time.sleep(0.2)
    return True


def last_line(name: str) -> str:
    try:
        lines = [x for x in (STATE_DIR / f"{name}.log").read_text(encoding="utf-8").splitlines() if x.strip()]
        return lines[-1][-160:] if lines else "the log is empty"
    except OSError:
        return "there is no log"


def _reach(host: str) -> str:
    """The address to reach a service at from this machine."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def autostart() -> list[str]:
    """Start every project that is on and not running: what /serve left on
    outlives a reboot. Lines saying what could not start."""
    if os.name == "nt":
        return []
    notes = []
    for name, entry in read_list().items():
        if entry.get("on") and not state_of(name):
            why = start(name, entry)
            if why:
                notes.append(f"{name} is on in /serve but could not start - {why}")
    return notes


# ── what the home screen says ────────────────────────────────────────────────

def home_rows() -> list[tuple[str, str]]:
    """(text, colour) for each served project, or [] when none is.

    Every time the home screen is drawn, so that nothing is left running
    unnoticed: green for one that runs, yellow for one that is on and does not,
    grey for one that is off.
    """
    listed = read_list()
    if not listed:
        return []
    width = min(24, max(len(n) for n in listed))
    out = []
    for name, entry in listed.items():
        where = f"{entry.get('host')}:{entry.get('port')}"
        lead = f"{name:<{width}}  "
        state = state_of(name)
        if not entry.get("on"):
            out.append((lead + f"off{SEP}{where}", GREY))
        elif state is None:
            out.append((lead + f"on, but not running{SEP}/serve", "\033[33m"))
        else:
            out.append((lead + f"{where}{SEP}{talking(state)}"
                        + ("" if entry.get("memory", True) else f"{SEP}memory off"), "\033[32m"))
    return out


def talking(state: dict) -> str:
    c = state.get("conversation")
    if not c:
        return "waiting"
    n = int(c.get("turns") or 0)
    return ("answering now" if c.get("busy") else
            f"a conversation, {n} turn{'' if n == 1 else 's'}")


# ── the page ─────────────────────────────────────────────────────────────────

def for_the_program(name: str, entry: dict) -> list[str]:
    host = str(entry.get("host") or "127.0.0.1")
    shown = _reach(host) if host in LOCAL else host
    if host in ("0.0.0.0", "::"):
        shown = "<this machine's address>"
    return [f"LLM_BASE_URL=http://{shown}:{entry.get('port')}/v1",
            f"LLM_MODEL=pragma:{name}",
            f"LLM_API_KEY={entry.get('key')}"]


def page() -> None:
    while True:
        listed = read_list()
        title("Serve", "projects other programs can talk to, as to a model")
        print()
        say("  A program that talks to an OpenAI-compatible endpoint can talk to a project", "dim")
        say("  instead: its memory, its folder, its tools. They keep running when Pragma", "dim")
        say("  is closed, until they are turned off here.", "dim")
        names = list(listed)
        width = max([len(n) for n in names] + [4])
        options, notes = [], []
        for name in names:
            entry = listed[name]
            state = state_of(name)
            options.append(f"{name:<{width}}")
            where = f"{entry.get('host')}:{entry.get('port')}"
            if not entry.get("on"):
                notes.append(f"off{SEP}{where}")
            elif state is None:
                notes.append(f"on, but not running{SEP}{where}")
            else:
                notes.append(f"on{SEP}{where}{SEP}{talking(state)}"
                             + ("" if entry.get("memory", True) else f"{SEP}memory off"))
        options.append("add")
        notes.append("serve another project")
        chosen = pick("", options, notes)
        if chosen is None:
            return
        if chosen == len(names):
            name = add(listed)
            if name:
                project_page(name)
            continue
        project_page(names[chosen])


def add(listed: dict) -> str:
    import pragma_launcher
    projects = [e["name"] for e in pragma_launcher.read_registry() if e["name"] not in listed]
    title("Serve", "add")
    if not projects:
        print()
        say("  Every project is already served." if listed else "  There are no projects yet - /new starts one.", "dim")
        pause()
        return ""
    i = pick("Which project?", projects)
    if i is None:
        return ""
    name = projects[i]
    listed[name] = {"host": "127.0.0.1", "port": free_port(listed),
                    "key": "pgk_" + secrets.token_urlsafe(18), "on": True}
    save_list(listed)
    title("Serve", f"add > {name}")
    print()
    with_waiting(f"starting {name}")
    why = start(name, listed[name])
    if why:
        say(f"  {name} is on the list, but {why}", "warn")
        pause()
    return name


def with_waiting(text: str) -> None:
    say(f"  {text}…", "dim")


def project_page(name: str) -> None:
    at = 0
    while True:
        listed = read_list()
        entry = listed.get(name)
        if entry is None:
            return
        state = state_of(name)
        title("Serve", name)
        print()
        a = accent()
        grey, reset = (GREY, RESET) if a else ("", "")
        if state:
            say(f"  running{SEP}{talking(state)}{SEP}{int(state.get('requests') or 0)} requests "
                "since it started", "good")
        elif entry.get("on"):
            say(f"  on, but not running - {last_line(name)}", "warn")
        else:
            say("  off", "dim")
        print()
        say("  For the program, in its settings or its .env:", "dim")
        for line in for_the_program(name, entry):
            print(f"    {line}")
        rows = ["state", "memory", "address", "port", "key", "log", "remove"]
        notes = ["on" if entry.get("on") else "off",
                 "on - recalled before each turn, written when a conversation ends"
                 if entry.get("memory", True) else
                 "off - the agent alone: nothing recalled, nothing written",
                 str(entry.get("host")) + ("  this machine only" if entry.get("host") in LOCAL
                                           else "  open to the network"),
                 str(entry.get("port")),
                 "a new one",
                 str(STATE_DIR / f"{name}.log").replace(str(Path.home()), "~"),
                 "stop serving it, and take it off the list"]
        chosen = pick("", rows, notes, start=at)
        if chosen is None:
            return
        at = chosen
        what = rows[chosen]
        if what == "state":
            if entry.get("on"):
                stop(name)
                entry["on"] = False
                save_list(listed)
            else:
                entry["on"] = True
                save_list(listed)
                print()
                with_waiting(f"starting {name}")
                why = start(name, entry)
                if why:
                    say(f"  {why}", "warn")
                    pause()
        elif what == "memory":
            entry["memory"] = not entry.get("memory", True)
            save_list(listed)
            _restart(name, entry)
        elif what in ("address", "port"):
            print()
            if what == "address":
                got = ask("Address", str(entry.get("host")),
                          hint="127.0.0.1 is this machine only; 0.0.0.0 opens it to the network")
            else:
                got = ask("Port", str(entry.get("port")), hint="a number from 1024 to 65535")
            if got is None or got == str(entry.get(what if what == "port" else "host")):
                continue
            if what == "port":
                if not got.isdigit() or not 1024 <= int(got) <= 65535:
                    say("  not a port", "warn")
                    pause()
                    continue
                if any(int(e.get("port") or 0) == int(got) for n, e in listed.items() if n != name):
                    say("  another served project has that port", "warn")
                    pause()
                    continue
                entry["port"] = int(got)
            else:
                entry["host"] = got.strip()
            save_list(listed)
            _restart(name, entry)
        elif what == "key":
            if confirm("A new key? The program will need it in place of the old one.", "yes, a new key"):
                entry["key"] = "pgk_" + secrets.token_urlsafe(18)
                save_list(listed)
                _restart(name, entry)
        elif what == "log":
            title("Serve", f"{name} > log")
            print()
            try:
                lines = (STATE_DIR / f"{name}.log").read_text(encoding="utf-8").splitlines()[-30:]
            except OSError:
                lines = ["there is no log yet"]
            for line in lines:
                print(f"  {grey}{line[:200]}{reset}")
            pause()
        elif what == "remove":
            if confirm(f"Stop serving {name}? A program using it will get no answer.",
                       "yes, stop and remove it"):
                stop(name)
                listed.pop(name, None)
                save_list(listed)
                return


def _restart(name: str, entry: dict) -> None:
    """A change of address, port or key counts when the service starts again."""
    if not entry.get("on"):
        return
    print()
    with_waiting(f"starting {name} again")
    stop(name)
    why = start(name, entry)
    if why:
        say(f"  {why}", "warn")
        pause()


def main() -> int:
    if "--autostart" in sys.argv[1:]:
        for note in autostart():
            print(f"  {note}")
        return 0
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        page()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
