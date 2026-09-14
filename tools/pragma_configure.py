#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""/configure: the endpoints Pragma can talk to, and which one serves each role.

Reached as /configure from the launcher's home prompt or inside a
conversation. It also runs on its own, for a machine being set up by hand:

    venv\Scripts\python.exe tools\pragma_configure.py

An endpoint is a server Pragma can talk to, kept under a name the operator
chooses. The page lists them with what each answers right now, and the three
roles: agent (the conversation), recall (the CURATOR, before each turn) and
memory (the faculties that write episodes and beliefs).

    /add                        a server: its address, then a name
    /edit [name]                model name or API key, or a new address
    /rename [name] [new]        call one something else
    /remove [name]              remove one no role uses
    /role <role|all> <name>     put a role, or all three, on an endpoint
    /test                       ask every endpoint again

Everything is kept in ~/.pragma/endpoints.json (core/endpoints.py reads it).
The page starts empty: until the first /add, Pragma goes on using the endpoint
written in .env, and says so. The first endpoint added takes every role, so
one /add is a complete setup; .env is never written from here.

Ctrl+D goes back, always: from the command line it leaves the page, and from
inside a question it abandons that command with nothing written. The exit code
says whether anything changed, 0 yes and 3 no; a change applies from the next
call, even in a conversation already running.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
# This page probes endpoints itself, with the answers it shows; config's
# import-time probe would only add a wait before the page appears.
os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")

import endpoints  # noqa: E402

CHANGED, UNCHANGED = 0, 3
GREY, RESET = "\033[38;5;242m", "\033[0m"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
CLEAR = "none"

COMMANDS = {
    "/add":    "add a server: its address, then a name",
    "/edit":   "model name, API key or address of one - /edit <name>",
    "/rename": "call one something else - /rename <name> <new name>",
    "/remove": "remove one no role uses - /remove <name>",
    "/role":   "put a role on an endpoint - /role <agent|recall|memory|all> <name>",
    "/test":   "ask every endpoint again",
    "/help":   "this list",
    "/done":   "go back (ctrl+D does the same)",
}
ROLE_BLURB = {
    "agent":  "the conversation",
    "recall": "the CURATOR, before each turn",
    "memory": "episodes and beliefs, in the background",
}


def colour(code: str) -> str:
    return code if sys.stdout.isatty() else ""


# ── the prompt ────────────────────────────────────────────────────────────────

def make_session(state: dict):
    """A prompt where Ctrl+D always goes back, with completion, or None."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None
    kb = KeyBindings()

    # On every line, typed on or not. prompt_toolkit's own Ctrl+D leaves only
    # from an empty line and deletes a character otherwise, so "always goes
    # back" would have been true exactly until someone started typing - which
    # is when people change their mind.
    @kb.add("c-d")
    def _back(event):
        event.app.exit(exception=EOFError)

    class ConfigureCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            words = text.split(" ")
            names = sorted(state["cat"]["endpoints"])
            if len(words) == 1:
                options = list(COMMANDS.items())
            elif words[0] in ("/edit", "/remove", "/rename") and len(words) == 2:
                options = [(n, "") for n in names]
            elif words[0] == "/role" and len(words) == 2:
                options = [(r, ROLE_BLURB[r]) for r in endpoints.ROLES] + [("all", "all three roles")]
            elif words[0] == "/role" and len(words) == 3:
                options = [(n, "") for n in names]
            else:
                return
            typed = words[-1]
            for value, meta in options:
                if value.startswith(typed):
                    yield Completion(value, start_position=-len(typed), display_meta=meta)

    return PromptSession(key_bindings=kb, completer=ConfigureCompleter(),
                         complete_while_typing=True, reserve_space_for_menu=6)


def ask(session, prompt: str, current: str = "", secret: bool = False,
        clearable: bool = False, hint: str = "") -> str:
    """One answer. Enter keeps `current`; "none" clears it when `clearable`.

    Raises EOFError on Ctrl+D. The current value (or a hint) and the way out
    are shown in grey where the answer goes, visible while nothing is typed.
    """
    if session is None:
        shown = ("set" if current else "") if secret else current
        reply = input(f"  {prompt}{f' [{shown}]' if shown else ''}: ").strip()
    else:
        from prompt_toolkit.formatted_text import ANSI
        if current:
            grey = ("a key is set" if secret else current) + " · enter keeps it"
            if clearable:
                grey += f" · {CLEAR} clears it"
        else:
            grey = hint or "empty"
        placeholder = ANSI(f"{GREY}{grey} · ctrl+D to go back{RESET}")
        reply = session.prompt(ANSI(f"  {prompt}: "), placeholder=placeholder,
                               is_password=secret).strip()
    if clearable and reply.lower() == CLEAR:
        return ""
    return reply or current


def command_line(session) -> str:
    if session is None:
        return input("  configure > ")
    from prompt_toolkit.formatted_text import ANSI
    a = colour("\033[38;2;178;132;255m")
    return session.prompt(
        ANSI(f"  {a}configure >{RESET if a else ''} "),
        placeholder=ANSI(f"{GREY}/add /edit /role /test · /help · ctrl+D to go back{RESET}"))


# ── the page ──────────────────────────────────────────────────────────────────

def role_target(cat: dict, role: str) -> tuple[str, bool]:
    """(endpoint name, explicitly assigned?) for a role."""
    roles = cat.get("roles") or {}
    if roles.get(role):
        return roles[role], True
    if roles.get("agent"):
        return roles["agent"], False
    names = list(cat.get("endpoints") or {})
    return (names[0] if names else ""), False


def show(state: dict) -> None:
    g, r = colour(GREY), colour(RESET)
    ok, bad = colour("\033[32m"), colour("\033[33m")
    cat = state["cat"]
    print()
    print(f"  {g}An endpoint is a server Pragma can talk to, under a name you choose.{r}")
    print(f"  {g}Each of the three roles below uses one of them.{r}")
    print()
    print(f"  {g}endpoints{r}")
    if not cat["endpoints"]:
        env = endpoints.env_endpoint()
        p = endpoints.probe(env)
        print("    none yet - /add one")
        print()
        print(f"  {g}Until you do, Pragma uses the endpoint written in .env:{r}")
        print(f"    {env.base_url}  {ok if p.get('up') else bad}{endpoints.status_text(p)}{r}")
        print()
        return
    eps = [endpoints.from_entry(n, e) for n, e in cat["endpoints"].items()]
    found = endpoints.probe_all(eps)
    width = max(len(ep.name) for ep in eps) + 2
    for ep in eps:
        p = found.get(ep.base_url, {})
        entry = cat["endpoints"][ep.name]
        note = []
        if entry.get("key_env"):
            note.append(f"key from ${entry['key_env']}")
        elif ep.api_key:
            note.append("key set")
        if ep.model:
            note.append(f"asks for {ep.model}")
        tail = f"  ({', '.join(note)})" if note else ""
        # The name on the line that says what it is, the address under it:
        # "connected" alone on its own line read as a status without an owner.
        print(f"    {ep.name:<{width}}{ok if p.get('up') else bad}{endpoints.status_text(p)}{r}")
        print(f"    {'':<{width}}{g}{ep.base_url}{tail}{r}")
    print()
    print(f"  {g}roles{r}")
    for role in endpoints.ROLES:
        name, explicit = role_target(cat, role)
        how = "" if explicit or role == "agent" else f"  {g}(follows agent){r}"
        print(f"    {role:<8}{name:<{width}}{g}{ROLE_BLURB[role]}{r}{how}")
    print()


# ── commands ──────────────────────────────────────────────────────────────────

def normalise_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "http://" + url
    after_host = url.split("://", 1)[1]
    if "/" not in after_host.rstrip("/"):
        url = url.rstrip("/") + "/v1"
    return url.rstrip("/")


def name_from_model(served: str) -> str:
    """"Qwen3.5-4B-GGUF:Q4_K_M" -> "qwen3.5-4b"; "" when nothing usable is served."""
    name = re.sub(r"[-_.]?gguf$", "", (served or "").split(":")[0], flags=re.I).lower()
    name = re.sub(r"[^a-z0-9._-]", "-", name).strip("-._")[:32]
    return name if NAME_RE.match(name or "") else ""


def check_name(cat: dict, name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValueError(f"'{name}' is not a usable name: letters, digits, '.', '-' and '_'")
    if name in cat["endpoints"]:
        raise ValueError(f"there is already an endpoint called '{name}'")
    return name


def which(session, cat, arg, verb):
    """The endpoint a command is about: the argument, the only one, or a question naming them."""
    names = sorted(cat["endpoints"])
    if not names:
        raise ValueError("there are no endpoints yet - /add one first")
    if arg:
        name = arg
    elif len(names) == 1:
        name = names[0]
    else:
        name = ask(session, f"Which endpoint to {verb} ({', '.join(names)})")
    if name not in cat["endpoints"]:
        raise ValueError(f"no endpoint called '{name}' - the names are {', '.join(names)}")
    return name


def cmd_add(session, state, arg):
    """Address first, so the server can be asked what it serves; the name follows from that."""
    cat = state["cat"]
    if arg:
        check_name(cat, arg)
    url = ask(session, "Address of the server", hint="e.g. 127.0.0.1:8100 - /v1 is added if missing")
    if not url:
        raise ValueError("a server needs an address")
    url = normalise_url(url)
    p = endpoints.probe(endpoints.Endpoint("new", url))
    print(f"  {url}  {colour(chr(27) + ('[32m' if p.get('up') else '[33m'))}"
          f"{endpoints.status_text(p)}{colour(RESET)}")
    name = arg
    if not name:
        suggestion = name_from_model(p.get("served", "")) or "main"
        while suggestion in cat["endpoints"]:
            suggestion += "-2"
        name = ask(session, "Name", hint=f"enter for {suggestion}") or suggestion
        check_name(cat, name)
    cat["endpoints"][name] = {"url": url}
    if not cat["roles"].get("agent"):
        cat["roles"]["agent"] = name
        state["note"] = f"{name} is the first endpoint, so all three roles use it"
    else:
        state["note"] = f"{name} added - /role <role> {name} to use it"
    return CHANGED


def cmd_edit(session, state, arg):
    cat = state["cat"]
    name = which(session, cat, arg, "edit")
    entry = cat["endpoints"][name]
    print(f"  {colour(GREY)}editing {name}{colour(RESET)}")
    url = ask(session, "Address", entry.get("url", ""))
    model = ask(session, "Model name", entry.get("model", ""), clearable=True,
                hint="empty: whatever the server serves")
    key_env = ask(session, "API key from an environment variable", entry.get("key_env", ""),
                  clearable=True, hint="its name, or empty")
    key = ""
    if not key_env:
        key = ask(session, "API key", entry.get("key", ""), secret=True, clearable=True,
                  hint="empty for local servers")
    new = {"url": normalise_url(url)}
    if model:
        new["model"] = model
    if key_env:
        new["key_env"] = key_env.lstrip("$")
    elif key:
        new["key"] = key
    cat["endpoints"][name] = new
    return CHANGED


def cmd_rename(session, state, arg):
    cat = state["cat"]
    parts = arg.split()
    old = which(session, cat, parts[0] if parts else "", "rename")
    new = check_name(cat, parts[1] if len(parts) > 1 else ask(session, f"New name for {old}"))
    cat["endpoints"] = {(new if n == old else n): e for n, e in cat["endpoints"].items()}
    cat["roles"] = {r: (new if n == old else n) for r, n in cat["roles"].items()}
    return CHANGED


def cmd_remove(session, state, arg):
    cat = state["cat"]
    name = which(session, cat, arg, "remove")
    users = [role for role, n in cat["roles"].items() if n == name]
    if users and len(cat["endpoints"]) > 1:
        raise ValueError(f"'{name}' serves {', '.join(users)} - move "
                         f"{'it' if len(users) == 1 else 'them'} first, e.g. /role all <other>")
    if ask(session, f"Remove '{name}'? y/N", hint="y to remove").lower() not in ("y", "yes", "s", "si"):
        return UNCHANGED
    del cat["endpoints"][name]
    cat["roles"] = {r: n for r, n in cat["roles"].items() if n != name}
    if not cat["endpoints"]:
        state["note"] = "no endpoints left: Pragma goes back to the one in .env"
    return CHANGED


def cmd_role(session, state, arg):
    cat = state["cat"]
    if not cat["endpoints"]:
        raise ValueError("there are no endpoints yet - /add one first")
    parts = arg.split()
    role = parts[0] if parts else ask(session, "Which role (agent, recall, memory, or all)")
    if role not in endpoints.ROLES and role != "all":
        raise ValueError(f"'{role}' is not a role: agent, recall, memory, or all")
    name = parts[1] if len(parts) > 1 else which(session, cat, "", f"use for {role}")
    if name not in cat["endpoints"]:
        raise ValueError(f"no endpoint called '{name}' - /add it first")
    for each in (endpoints.ROLES if role == "all" else (role,)):
        cat["roles"][each] = name
    return CHANGED


HANDLERS = {"/add": cmd_add, "/edit": cmd_edit, "/rename": cmd_rename,
            "/remove": cmd_remove, "/role": cmd_role}


def save(state: dict) -> None:
    """The file, or no file: an empty catalogue means "use .env", so it is removed."""
    cat = state["cat"]
    path = endpoints.catalogue_path()
    if cat["endpoints"]:
        endpoints.save_catalogue(cat)
    elif path.exists():
        path.unlink()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    data, error = endpoints.load_catalogue()
    if error:
        print(f"  {colour(chr(27) + '[33m')}the endpoint file cannot be read:{colour(RESET)}")
        print(f"    {error}")
        print("  Fix it by hand, or type /reset to set it aside and start again.")
        print()
    cat = {"endpoints": dict((data or {}).get("endpoints") or {}),
           "roles": dict((data or {}).get("roles") or {})}
    state = {"cat": cat, "broken": bool(error)}
    session = make_session(state)
    if not error:
        show(state)

    changed = False
    while True:
        try:
            line = command_line(session).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        head, _, rest = line.partition(" ")
        cmd = head.lower() if head.startswith("/") else "/" + head.lower()
        if cmd in ("/done", "/exit", "/back", "/q"):
            break
        if cmd == "/help":
            print()
            for name, blurb in COMMANDS.items():
                print(f"    {name:<9}{blurb}")
            print()
            continue
        if cmd == "/reset" and state["broken"]:
            path = endpoints.catalogue_path()
            aside = path.with_name(path.name + ".broken")
            os.replace(path, aside)
            print(f"  set aside as {aside}")
            state["broken"] = False
            show(state)
            continue
        if state["broken"]:
            print("  the endpoint file cannot be read - fix it, or /reset")
            continue
        if cmd == "/test":
            show(state)
            continue
        handler = HANDLERS.get(cmd)
        if handler is None:
            print(f"  {head} is not a command here. /help lists them.")
            continue
        before = {"endpoints": dict(cat["endpoints"]), "roles": dict(cat["roles"])}
        state.pop("note", None)
        try:
            what = handler(session, state, rest.strip())
            if what == CHANGED:
                save(state)
                changed = True
        except (EOFError, KeyboardInterrupt):
            cat.update(before)
            print()
            print("  back - nothing changed.")
            continue
        except (ValueError, endpoints.EndpointError) as e:
            cat.update(before)
            print(f"  {e}")
            continue
        if what == CHANGED:
            show(state)
            if state.get("note"):
                print(f"  {state['note']}")
                print()

    return CHANGED if changed else UNCHANGED


if __name__ == "__main__":
    sys.exit(main())
