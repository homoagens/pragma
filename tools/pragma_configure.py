#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""/configure: the servers Pragma talks to, and everything about each one.

Reached as /configure from the launcher's home prompt, on either system. It
also runs on its own, for a machine being set up by hand:

    venv\Scripts\python.exe tools\pragma_configure.py

WHAT IS HERE AND WHY IT IS ALL HERE. An endpoint is a server under a name you
choose. The machine at that address is running one model: it either reasons or
it does not, it is being used for conversation or for code, and there is one
set of numbers worth sending it. None of that changes when a project opens, so
none of it is a project's setting - it is written here, once, beside the
address, and every project that talks to that endpoint inherits it.

    add      a server: its address, its name, what it is, how it samples
    use      one endpoint for all three roles - the usual setup
    roles    a different endpoint per role
    tune     what the model is, what it is for, and the knobs it sends
    edit     address, model name, API key
    remove   an endpoint no role needs
    test     ask every endpoint again

The three roles are agent (the conversation), recall (the CURATOR, before each
turn) and memory (the faculties that write episodes and beliefs).

TUNING HAS THREE WAYS IN, because the three are different amounts of knowing:

    standard   send nothing; the server keeps the numbers it was started with
    advanced   type them yourself, row by row
    ask it     let the model read its own card on HuggingFace and fill them in

The last one asks the endpoint - with no knobs, so it answers as it was
started - to read the model card of the model it is serving and translate its
recommendations into the four rows. What it proposes is shown before anything
is written, because a model quoting a table it half remembers is exactly the
failure this is meant to catch.

Everything is kept in ~/.pragma/endpoints.json (core/endpoints.py reads it).
The page starts empty: until the first add, Pragma goes on using the endpoint
written in .env, and says so. The first endpoint added takes every role, so
one add is a complete setup; .env is never written from here.

Ctrl+D goes back, always: out of a question with nothing written, out of the
page from the menu. The exit code says whether anything changed, 0 yes and 3
no; a change applies from the next call, even in a conversation already
running.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]
# This page probes endpoints itself, with the answers it shows; config's
# import-time probe would only add a wait before the page appears.
os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")

import endpoints  # noqa: E402
from pragma_menu import (GREY, RESET, accent, ask, choose, clear, confirm,  # noqa: E402
                         pick, say, title)

CHANGED, UNCHANGED = 0, 3
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
ROLE_BLURB = {
    "agent":  "the conversation",
    "recall": "the CURATOR, before each turn",
    "memory": "episodes and beliefs, in the background",
}
KIND_BLURB = {
    "thinking": "it reasons before it answers: slower, better on problems",
    "instruct": "it answers at once: a conversation feels this on every turn",
}
WORK_BLURB = {
    "general": "conversation, reading, reasoning about a problem",
    "coding":  "writing and fixing code: cooler, less wandering",
}
KNOB_BLURB = {
    "temperature":      "how far from the most likely word it will go",
    "top_p":            "keep the words that make up this much of the mass",
    "top_k":            "keep at most this many words",
    "min_p":            "drop words this much less likely than the best one",
    "presence_penalty": "push against words already used",
    "repeat_penalty":   "push against repeating, harder the more it repeats",
}


def ok_bad(up: bool) -> str:
    if not sys.stdout.isatty():
        return ""
    return "\033[32m" if up else "\033[33m"


def off() -> str:
    return RESET if sys.stdout.isatty() else ""


def grey(text: str) -> str:
    return f"{GREY}{text}{RESET}" if accent() else text


# -- the page -----------------------------------------------------------------

def role_target(cat: dict, role: str) -> tuple[str, bool]:
    """(endpoint name, explicitly assigned?) for a role."""
    roles = cat.get("roles") or {}
    if roles.get(role):
        return roles[role], True
    if roles.get("agent"):
        return roles["agent"], False
    names = list(cat.get("endpoints") or {})
    return (names[0] if names else ""), False


def knob_text(knobs: dict) -> str:
    """The numbers, in the order they are worth reading, or ""."""
    order = [k for k in endpoints.KNOBS if k in knobs]
    return ", ".join(f"{k} {knobs[k]:g}" for k in order)


def nature(entry: dict) -> str:
    """One line: what this endpoint is, what it is for, what it sends."""
    kind, work = entry.get("kind"), entry.get("work")
    if not kind and not work and not entry.get("sampling"):
        return "not tuned yet - what it is, and how it samples"
    words = f"{kind or 'kind not set'} . {work or 'general'}"
    if not entry.get("sampling"):
        return f"{words} . the server's own numbers"
    sent = knob_text(endpoints.sampling_row(entry))
    return f"{words} . {sent}" if sent else f"{words} . the server's own numbers"


def step(crumbs: str = "") -> None:
    """A page of its own for every question. See pragma_menu.title."""
    title("Configure", crumbs)


def show(state: dict) -> None:
    """The whole page: what each endpoint is, and who uses it."""
    cat = state["cat"]
    step()
    print()
    print("  " + grey("An endpoint is a server Pragma can talk to, under a name you choose."))
    print("  " + grey("What it is and how it samples are written here, not in a project."))
    print()
    if not cat["endpoints"]:
        env = endpoints.env_endpoint()
        p = endpoints.probe(env)
        print("  " + grey("endpoints"))
        print("    none yet - add one")
        print()
        print("  " + grey("Until you do, Pragma uses the endpoint written in .env:"))
        print(f"    {env.base_url}  {ok_bad(p.get('up'))}{endpoints.status_text(p)}{off()}")
        print()
        return
    eps = [endpoints.from_entry(n, e) for n, e in cat["endpoints"].items()]
    found = endpoints.probe_all(eps)
    width = max(len(ep.name) for ep in eps) + 2
    print("  " + grey("endpoints"))
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
        print(f"    {ep.name:<{width}}{ok_bad(p.get('up'))}{endpoints.status_text(p)}{off()}")
        print(f"    {'':<{width}}" + grey(ep.base_url + tail))
        print(f"    {'':<{width}}" + grey(nature(entry)))
    print()
    print("  " + grey("roles"))
    for role in endpoints.ROLES:
        name, explicit = role_target(cat, role)
        how = "" if explicit or role == "agent" else "  " + grey("(follows agent)")
        print(f"    {role:<8}{name:<{width}}" + grey(ROLE_BLURB[role]) + how)
    told = state.pop("note", "")
    if told:
        print()
        say(f"  {told}", "good")


# -- naming and addresses -----------------------------------------------------

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


def rename(cat: dict, old: str, new: str) -> None:
    """Called something else, in the catalogue and in every role that uses it."""
    if new == old:
        return
    check_name(cat, new)
    cat["endpoints"] = {(new if n == old else n): e for n, e in cat["endpoints"].items()}
    cat["roles"] = {r: (new if n == old else n) for r, n in cat["roles"].items()}


def which(cat: dict, question: str, crumbs: str = "") -> str | None:
    """The endpoint a command is about, chosen from the list.

    With one endpoint there is nothing to choose and nothing is drawn: a page
    that asks a question with a single answer is a page that wastes a keypress.
    """
    names = sorted(cat["endpoints"])
    if not names:
        raise ValueError("there are no endpoints yet - add one first")
    if len(names) == 1:
        return names[0]
    step(crumbs)
    notes = [nature(cat["endpoints"][n]) for n in names]
    i = pick(question, names, notes)
    return None if i is None else names[i]


# -- what a model is, and the numbers it sends --------------------------------

def edit_row(entry: dict, kind: str, work: str, name: str = "") -> None:
    """One row of the table, knob by knob. Enter keeps, `-` hands it back."""
    table = entry.setdefault("sampling", {}).setdefault(kind, {})
    row = dict(table.get(work) or {})
    step(f"tune > {name} > sampling > {kind} . {work}" if name
         else f"sampling > {kind} . {work}")
    print()
    print("  " + grey("Six knobs, asked in order. Every one of them is MEASURED to"))
    print("  " + grey("arrive: what the server ignores is not on this page at all."))
    print()
    print("  " + grey("enter keeps what is in brackets . `-` hands that one back to"))
    print("  " + grey("the server . ctrl+D stops here and keeps the answers above"))
    print()
    print("  " + grey("now: " + (knob_text(row) or "nothing - the server decides all six")))
    print()
    for knob in endpoints.KNOBS:
        current = row.get(knob)
        shown = f"{current:g}" if current is not None else "the server's"
        say(f"    {KNOB_BLURB[knob]}", "dim")
        answer = ask(f"  {knob}", "", hint=f"[{shown}]")
        if answer is None:
            break
        answer = answer.strip()
        if not answer:
            continue
        if answer == "-":
            row.pop(knob, None)
            continue
        try:
            row[knob] = float(answer)
        except ValueError:
            say(f"    {answer!r} is not a number - left as it was", "warn")
    table[work] = row


def advanced(entry: dict, name: str = "") -> None:
    """The four rows, as a list: whichever one you want to write."""
    while True:
        step(f"tune > {name} > sampling > advanced" if name else "sampling > advanced")
        rows, labels, notes = [], [], []
        for kind in endpoints.KINDS:
            for work in endpoints.FLAVOURS:
                rows.append((kind, work))
                labels.append(f"{kind} . {work}")
                sent = knob_text((entry.get("sampling", {}).get(kind) or {}).get(work) or {})
                notes.append(sent or "nothing: the server decides")
        labels.append("done")
        notes.append("")
        i = pick("Which row?", labels, notes)
        if i is None or i == len(rows):
            return
        edit_row(entry, *rows[i], name=name)


# -- asking the model about itself --------------------------------------------

def fetch(url: str, timeout: float = 15.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "pragma/configure"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return answer.read().decode("utf-8", "replace")


def served_alias(ep) -> str:
    """The repository name the server was started from, when it says.

    llama.cpp answers /props with `model_alias`, which for a GGUF started by
    name is the HuggingFace path - "unsloth/Qwen3.6-35B-A3B-MTP-GGUF:UD-Q5_K_M".
    That is the only place the ORIGINAL name survives: /models reports the
    file, and a file name has had the org taken off it.
    """
    root = ep.base_url[:-3] if ep.base_url.endswith("/v1") else ep.base_url
    try:
        props = json.loads(fetch(root.rstrip("/") + "/props", timeout=5))
    except Exception:
        return ""
    for key in ("model_alias", "model_path", "model"):
        value = str(props.get(key) or "")
        if "/" in value.replace("\\", "/"):
            return value
    return ""


def card(alias: str) -> tuple[str, str]:
    """(where it was read, the text) for the model's page on HuggingFace.

    A quantised repository is tried first, because that is the one the server
    names, and then the same name without the -GGUF suffix: the people who
    publish quantisations copy the card, but not always, and the original is
    where the recommendation actually lives.
    """
    repo = alias.replace("\\", "/").split(":")[0].strip("/")
    parts = [p for p in repo.split("/") if p]
    if len(parts) < 2:
        return "", ""
    repo = "/".join(parts[-2:])
    tries = [repo]
    bare = re.sub(r"[-_.]?gguf$", "", repo, flags=re.I)
    if bare != repo:
        tries.append(bare)
    for candidate in tries:
        for name in ("README.md", "generation_config.json"):
            url = f"https://huggingface.co/{candidate}/raw/main/{name}"
            try:
                text = fetch(url)
            except Exception:
                continue
            if text.strip():
                return url, text[:24000]
    return "", ""


ASK_THE_MODEL = """You are running on a server, and someone is setting up a client for you.

Read the model card below and report the sampling settings IT recommends.

Answer with one JSON object and nothing else:

{"kind": "thinking" or "instruct",
 "thinking": {"general": {}, "coding": {}},
 "instruct": {"general": {}, "coding": {}}}

"kind" is what this model is: does it reason before answering, or answer at once?
Each inner object may set only these, all numbers:
  temperature, top_p, top_k, min_p, presence_penalty, repeat_penalty

RULES, and they matter more than filling the shape:
- Only numbers the card actually gives. Leave a setting out when it is not named.
- Leave a whole object empty when the card says nothing about that case.
- A card that gives one set of numbers for thinking and one for non-thinking
  puts them in "thinking" and "instruct"; put its coding advice, if it gives
  any, in "coding", and leave "coding" empty when it gives none.
- Do not convert, do not average, do not invent a number that looks sensible.

The model is: {alias}

--- the card ---
{card}
"""


def ask_the_model(ep, entry: dict, name: str = "") -> bool:
    """Let the endpoint read its own card and propose the four rows."""
    step(f"tune > {name} > sampling > ask it" if name else "sampling > ask it")
    print()
    say("  asking the server what it is serving...", "dim")
    alias = served_alias(ep)
    if not alias:
        say("  The server does not say which repository it was started from.", "warn")
        print("  " + grey("llama.cpp reports it in /props as model_alias; a model"))
        print("  " + grey("started from a plain file path has no name left to look up."))
        ask("", hint="enter to go back")
        return False
    say(f"  {alias}", "dim")
    say("  reading its page on HuggingFace...", "dim")
    where, text = card(alias)
    if not text:
        say("  That page could not be read - no network, or it is not public.", "warn")
        ask("", hint="enter to go back")
        return False
    say(f"  {where}", "dim")
    say("  asking the model to read its own card... (this takes a moment)", "dim")
    prompt = ASK_THE_MODEL.replace("{alias}", alias).replace("{card}", text)
    payload = {
        "model": ep.model or "",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    if not payload["model"]:
        payload.pop("model")
    headers = {"Content-Type": "application/json"}
    if ep.api_key:
        headers["Authorization"] = f"Bearer {ep.api_key}"
    try:
        request = urllib.request.Request(
            ep.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(request, timeout=300) as answer:
            body = json.loads(answer.read().decode("utf-8", "replace"))
        said = body["choices"][0]["message"]["content"] or ""
    except Exception as e:
        say(f"  The endpoint did not answer: {e}", "warn")
        ask("", hint="enter to go back")
        return False
    found = re.search(r"\{.*\}", said, re.S)
    try:
        proposed = json.loads(found.group(0)) if found else {}
    except Exception:
        proposed = {}
    if not isinstance(proposed, dict):
        proposed = {}
    table = {}
    for kind in endpoints.KINDS:
        rows = proposed.get(kind)
        if not isinstance(rows, dict):
            continue
        for work in endpoints.FLAVOURS:
            knobs = rows.get(work)
            if not isinstance(knobs, dict):
                continue
            clean = {k: float(v) for k, v in knobs.items()
                     if k in endpoints.KNOBS and isinstance(v, (int, float))
                     and not isinstance(v, bool)}
            if clean:
                table.setdefault(kind, {})[work] = clean
    kind = proposed.get("kind") if proposed.get("kind") in endpoints.KINDS else ""
    if not table and not kind:
        say("  It answered, but not with numbers this page can use:", "warn")
        print("    " + grey(" ".join(said.split())[:300]))
        ask("", hint="enter to go back")
        return False
    step(f"tune > {name} > sampling > ask it" if name else "sampling > ask it")
    print()
    say("  What it read off the card:", "accent")
    print()
    if kind:
        print(f"    it says it is {kind}")
    for half in endpoints.KINDS:
        for work in endpoints.FLAVOURS:
            sent = knob_text((table.get(half) or {}).get(work) or {})
            print(f"    {half} . {work:<8} " + (sent or grey("nothing")))
    print()
    say("  A model quoting its own card can get this wrong. Read it before saying yes.", "dim")
    if not confirm("Write these numbers?", "yes, write them", "no, leave it alone"):
        return False
    if kind:
        entry["kind"] = kind
    if table:
        entry["sampling"] = table
    else:
        entry.pop("sampling", None)
    return True


# -- the actions --------------------------------------------------------------

def tune(state: dict, name: str) -> bool:
    """What the endpoint is, what it is for, and how it samples."""
    cat = state["cat"]
    entry = cat["endpoints"][name]
    changed = False
    while True:
        sampling = ("the server's own numbers" if not entry.get("sampling")
                    else knob_text(endpoints.sampling_row(entry)) or "nothing set yet")
        step(f"tune > {name}")
        print()
        print("  " + grey(entry.get("url", "")))
        print("  " + grey("What this endpoint is. Every project that talks to it"))
        print("  " + grey("inherits these three answers."))
        i = pick("",
                 [f"what it is      {entry.get('kind') or 'not set'}",
                  f"what it is for  {entry.get('work') or 'general'}",
                  f"sampling        {sampling}",
                  "done"],
                 ["a reasoning model, or one that answers at once",
                  "conversation, or writing code",
                  "the knobs every request carries",
                  ""])
        if i is None or i == 3:
            return changed
        if i == 0:
            step(f"tune > {name} > what it is")
            got = choose("Does this model reason before it answers?",
                         [(k, KIND_BLURB[k]) for k in endpoints.KINDS],
                         entry.get("kind", ""))
            if got:
                entry["kind"] = got
                changed = True
        elif i == 1:
            step(f"tune > {name} > what it is for")
            got = choose("What is this endpoint used for?",
                         [(w, WORK_BLURB[w]) for w in endpoints.FLAVOURS],
                         entry.get("work", "general"))
            if got:
                entry["work"] = got
                changed = True
        else:
            step(f"tune > {name} > sampling")
            how = choose("How should it be sampled?", [
                ("standard", "send nothing: the server keeps what it was started with"),
                ("advanced", "type the numbers yourself, row by row"),
                ("ask it",   "the model reads its own card on HuggingFace and fills them in"),
            ])
            if how == "standard":
                entry.pop("sampling", None)
                changed = True
            elif how == "advanced":
                advanced(entry, name)
                changed = True
            elif how == "ask it":
                if ask_the_model(endpoints.from_entry(name, entry), entry, name):
                    changed = True
        if changed:
            save(state)


def cmd_add(state: dict) -> bool:
    """Address first, so the server can be asked what it serves; the name follows."""
    cat = state["cat"]
    step("add")
    print()
    print("  " + grey("The address first, so the server can be asked what it is"))
    print("  " + grey("serving - the name is suggested from its answer."))
    print()
    url = ask("Address of the server", hint="e.g. 127.0.0.1:8100 - /v1 is added if missing")
    if not url:
        return False
    url = normalise_url(url)
    p = endpoints.probe(endpoints.Endpoint("new", url))
    print(f"  {url}  {ok_bad(p.get('up'))}{endpoints.status_text(p)}{off()}")
    suggestion = name_from_model(p.get("served", "")) or "main"
    while suggestion in cat["endpoints"]:
        suggestion += "-2"
    name = ask("Name", suggestion)
    if name is None:
        return False
    check_name(cat, name)
    cat["endpoints"][name] = {"url": url}
    first = not cat["roles"].get("agent")
    if first:
        for role in endpoints.ROLES:
            cat["roles"][role] = name
    save(state)
    tune(state, name)
    state["note"] = (f"{name} added - the first endpoint, so all three roles use it"
                     if first else f"{name} added")
    return True


def cmd_use(state: dict) -> bool:
    """One endpoint for all three roles: what most setups are."""
    cat = state["cat"]
    name = which(cat, "Which endpoint should serve everything?", "use")
    if name is None:
        return False
    for role in endpoints.ROLES:
        cat["roles"][role] = name
    state["note"] = f"all three roles now use {name}"
    return True


def cmd_roles(state: dict) -> bool:
    """A role at a time, for the setups that split them across machines."""
    cat = state["cat"]
    changed = False
    while True:
        labels = []
        for role in endpoints.ROLES:
            who, explicit = role_target(cat, role)
            labels.append(f"{role:<8} {who}" + ("" if explicit or role == "agent"
                                                else "   (follows agent)"))
        labels.append("done")
        step("roles")
        print()
        print("  " + grey("One endpoint each, for a setup split across machines."))
        i = pick("", labels, [ROLE_BLURB[r] for r in endpoints.ROLES] + [""])
        if i is None or i == len(endpoints.ROLES):
            return changed
        role = endpoints.ROLES[i]
        name = which(cat, f"Which endpoint serves {role}?", f"roles > {role}")
        if name:
            cat["roles"][role] = name
            changed = True
            save(state)


def cmd_edit(state: dict) -> bool:
    """The address, the name, the model it is asked for, the key."""
    cat = state["cat"]
    name = which(cat, "Which endpoint?", "edit")
    if name is None:
        return False
    entry = cat["endpoints"][name]
    step(f"edit > {name}")
    print()
    print("  " + grey("What it is and how it samples are not here: those are `tune`."))
    print("  " + grey("enter keeps what is in brackets . ctrl+D stops"))
    print()
    # The name is asked first. Someone who opened this to call an endpoint
    # something else would otherwise find no name here at all, and typing the
    # new one into "model name" quietly asks the server for a model it does
    # not serve.
    new_name = ask("Name", name)
    if new_name is None:
        return False
    if new_name != name:
        check_name(cat, new_name)
    url = ask("Address", entry.get("url", ""))
    if url is None:
        return False
    model = ask("Model name", entry.get("model", ""),
                hint="[whatever the server serves] - `-` clears it")
    if model is None:
        return False
    key_env = ask("API key from an environment variable", entry.get("key_env", ""),
                  hint="[none] - its name, or `-` to clear")
    if key_env is None:
        return False
    key = entry.get("key", "")
    if not key_env.strip("-"):
        import getpass
        try:
            typed = getpass.getpass("  API key (empty for local servers, `-` clears): ")
        except (EOFError, KeyboardInterrupt):
            return False
        if typed.strip():
            key = "" if typed.strip() == "-" else typed.strip()
    new = {"url": normalise_url(url)}
    if model.strip() and model.strip() != "-":
        new["model"] = model.strip()
    if key_env.strip() and key_env.strip() != "-":
        new["key_env"] = key_env.strip().lstrip("$")
    elif key:
        new["key"] = key
    for keep in ("kind", "work", "sampling"):
        if entry.get(keep):
            new[keep] = entry[keep]
    cat["endpoints"][name] = new
    rename(cat, name, new_name)
    state["note"] = f"{new_name} saved"
    return True


def cmd_remove(state: dict) -> bool:
    cat = state["cat"]
    name = which(cat, "Which endpoint should go?", "remove")
    if name is None:
        return False
    users = [role for role, n in cat["roles"].items() if n == name]
    if users and len(cat["endpoints"]) > 1:
        raise ValueError(f"'{name}' serves {', '.join(users)} - move "
                         f"{'it' if len(users) == 1 else 'them'} first, with roles or use")
    step(f"remove > {name}")
    print()
    print("  " + grey(cat["endpoints"][name].get("url", "")))
    if not confirm(f"Remove '{name}'?", f"yes, remove {name}"):
        return False
    del cat["endpoints"][name]
    cat["roles"] = {r: n for r, n in cat["roles"].items() if n != name}
    state["note"] = (f"{name} removed" if cat["endpoints"]
                     else "no endpoints left: Pragma goes back to the one in .env")
    return True


ACTIONS = [
    ("add",    "a server: its address, its name, what it is", cmd_add),
    ("use",    "one endpoint for all three roles", cmd_use),
    ("roles",  "a different endpoint for each role", cmd_roles),
    ("tune",   "what the model is, what it is for, how it samples", None),
    ("edit",   "address, model name, API key", cmd_edit),
    ("remove", "an endpoint no role needs", cmd_remove),
    ("test",   "ask every endpoint again", None),
    ("done",   "go back", None),
]


def save(state: dict) -> None:
    """The file, or no file: an empty catalogue means "use .env", so it goes."""
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
        step()
        print()
        print(f"  {ok_bad(False)}The endpoint file cannot be read:{off()}")
        print(f"    {error}")
        print("  Fix it by hand, or move it aside from this page.")
        aside = confirm("Set it aside and start again?", "yes, set it aside")
        if not aside:
            return UNCHANGED
        path = endpoints.catalogue_path()
        os.replace(path, path.with_name(path.name + ".broken"))
        data = None
    cat = {"endpoints": dict((data or {}).get("endpoints") or {}),
           "roles": dict((data or {}).get("roles") or {})}
    state = {"cat": cat}

    old = Path.home() / ".pragma" / "sampling.json"
    if old.is_file():
        state["note"] = (f"{old} is no longer read - sampling lives beside "
                         f"each endpoint now, under tune")

    changed = False
    while True:
        show(state)
        i = pick("", [a for a, _, _ in ACTIONS], [b for _, b, _ in ACTIONS])
        if i is None or ACTIONS[i][0] == "done":
            clear()
            return CHANGED if changed else UNCHANGED
        action, _, handler = ACTIONS[i]
        if action == "test":
            # show() probes them all on the way round, so this asks for
            # nothing except the page being drawn again.
            state["note"] = "asked them all again"
            continue
        before = {"endpoints": json.loads(json.dumps(cat["endpoints"])),
                  "roles": dict(cat["roles"])}
        try:
            if action == "tune":
                name = which(cat, "Which endpoint?", "tune")
                did = bool(name and tune(state, name))
            else:
                did = bool(handler(state))
            if did:
                save(state)
                changed = True
        except (EOFError, KeyboardInterrupt):
            cat.update(before)
            state["note"] = ""
        except (ValueError, endpoints.EndpointError) as e:
            cat.update(before)
            print()
            say(f"  {e}", "warn")
            ask("", hint="enter to go back")


if __name__ == "__main__":
    sys.exit(main())
