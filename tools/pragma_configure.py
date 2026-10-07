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

THE PAGE IS ITS ENDPOINTS. Each is a row: its name, the roles it serves, and
under it what answers there, where, and what it is. Enter on one opens it,
and every row of ITS page is one question -

    serves           the roles that ask this server
    what it is       a model that reasons, or one that answers at once
    what it is for   conversation, or code
    who reasons      which roles are asked to, on a model that can
    sampling         the knobs every request carries
    name, address, model, API key
    remove

Under the endpoints, `add` and the three switches that are the harness's
rather than one server's.

The four roles are agent (the conversation), recall (the CURATOR, before each
turn), memory (the faculties that write episodes and beliefs) and critic (the
CRITIC, which judges the work before it is delivered). A role nobody assigns
follows the agent.

TUNING HAS THREE WAYS IN, because the three are different amounts of knowing:

    standard   send nothing; the server keeps the numbers it was started with
    advanced   type them yourself, row by row
    ask it     let the model read its own card on HuggingFace and fill them in

They are the three answers to the `sampling` row.

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
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]
# This page probes endpoints itself, with the answers it shows; config's
# import-time probe would only add a wait before the page appears.
os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")

import endpoints  # noqa: E402
from pragma_menu import (GREY, RESET, accent, ask, choose, clear,  # noqa: E402
                         columns, confirm, pick, say, title, waiting)

CHANGED, UNCHANGED = 0, 3
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
ROLE_BLURB = {
    "agent":  "the conversation",
    "recall": "the CURATOR, before each turn",
    "memory": "episodes and beliefs, in the background",
    "critic": "the CRITIC, before the answer is delivered",
}
KIND_BLURB = {
    "thinking": "it reasons before it answers: slower, better on problems",
    "instruct": "it answers at once: a conversation feels this on every turn",
}
WORK_BLURB = {
    "general": "conversation, reading, reasoning about a problem",
    "coding":  "writing and fixing code: cooler, less wandering",
}
# WHO REASONS. The roles endpoints.py routes by, said in terms of what
# the person actually waits for. Only shown for a thinking endpoint: an
# instruct one has nothing to switch.
#
# A table of its own, under its own name. It was a second ROLE_BLURB, and a
# second assignment to a name replaces the first: the page that asks what an
# endpoint SERVES had been showing these lines about waiting ever since, and
# the table written for it above was shown nowhere.
REASONS_BLURB = {
    "agent":  "the steps of the conversation: reading, editing, running",
    "recall": "choosing what to bring back from memory, every turn",
    "memory": "writing and revising what is remembered, after the turn",
    "critic": "judging the work against what was asked, before the answer",
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


def wrapped(text: str, colour: str = "", indent: int = 6) -> list[str]:
    """A line that belongs under a name, as the lines it takes in this window.

    Wrapped at words and never handed to the terminal to break: an address
    split as ".../" and "v1" at the last column, with the rest at the left
    edge, is what that looks like.
    """
    import textwrap
    room = max(20, columns() - 1 - indent)
    paint = colour if (colour and sys.stdout.isatty()) else ""
    return [f"{paint}{part}{RESET}" if paint else part
            for part in textwrap.wrap(text, room, break_on_hyphens=False) or [""]]


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


def config_base_url() -> str:
    """The address someone actually set, or "" when nothing did."""
    try:
        import config
        return str(config.LLM_BASE_URL or "").strip()
    except Exception:
        return ""


def nature(entry: dict) -> str:
    """One line: what this endpoint is, what it is for, what it sends."""
    kind, work = entry.get("kind"), entry.get("work")
    if not kind and not work and not entry.get("sampling"):
        return "not tuned yet - what it is, and how it samples"
    words = f"{kind or 'kind not set'} · {work or 'general'}"
    # Said only when it is news: when the endpoint's table differs from what
    # "thinking" means by default (the agent and the memory reason, the
    # recall answers at once). Repeating the default on every line would bury
    # the case that differs.
    who = reasons_text(entry)
    if who and entry.get("reasons"):
        words += f" ({who} reason)" if who != "nobody" else " (nobody reasons)"
    if not entry.get("sampling"):
        return f"{words} · the server's own numbers"
    sent = knob_text(endpoints.sampling_row(entry))
    return f"{words} · {sent}" if sent else f"{words} · the server's own numbers"


def step(crumbs: str = "") -> None:
    """A page of its own for every question. See pragma_menu.title."""
    title("Configure", crumbs)


def roles_of(cat: dict, name: str) -> str:
    """The roles this endpoint serves, as a tag to put beside its name.

    Beside the name, not in a block of their own underneath. The block listed
    three roles and repeated the endpoint names to do it, so the page said
    every name twice and the eye had to match them up. What a role IS belongs
    on the page you assign it from; what a server DOES belongs next to the
    server.
    """
    serving = [r for r in endpoints.ROLES if role_target(cat, r)[0] == name]
    if len(serving) == len(endpoints.ROLES):
        return "everything"
    return " ".join(serving)


_ASKED_FOR = 20          # seconds an endpoint's answer is shown again unasked


def answers(state: dict, eps: list) -> dict:
    """What each of these endpoints answers, by address.

    Every page that names a server says whether it answers, and one that is
    switched off takes three seconds to say that it is. Asked afresh by every
    page, a look inside an endpoint and back was two waits on an empty
    screen. An answer is kept for a few seconds; an address that has not been
    asked is asked at once, and so is everything after an address or a key
    has changed.
    """
    kept = state.get("answers") or {}
    stale = time.time() - state.get("asked", 0.0) > _ASKED_FOR
    if stale or any(ep.base_url not in kept for ep in eps):
        with waiting("asking the server" + ("" if len(eps) == 1 else "s")):
            kept = endpoints.probe_all(eps)
        state["answers"], state["asked"] = kept, time.time()
    return kept


def key_text(entry: dict) -> str:
    if entry.get("key_env"):
        return f"from ${entry['key_env']}"
    return "set" if entry.get("key") else "none"


def front(state: dict, at: tuple) -> tuple | None:
    """The page: every endpoint, `add`, and the harness's switches. Returns
    what was chosen - ("endpoint", name) or ("action", word) - or None.

    THE ENDPOINTS ARE THE ROWS. They used to be drawn above a list of verbs -
    add, remove, endpoints - and `endpoints` opened the same drawing above
    three more, each of which then asked "which endpoint?" with the names a
    third time. A server is chosen where it is shown, once; what can be asked
    about it is on its own page.
    """
    cat = state["cat"]
    step()
    eps = ([endpoints.from_entry(n, e) for n, e in cat["endpoints"].items()]
           or [endpoints.env_endpoint()])
    found = answers(state, eps)
    told = state.pop("note", "")
    if told:
        print()
        say(f"  {told}", "good")
    options, notes, under, what = [], [], [], []

    def put(option: str = "", note: str = "", lines=(), means: tuple | None = None) -> None:
        options.append(option)
        notes.append(note)
        under.append(list(lines))
        what.append(means)

    if not cat["endpoints"]:
        p = found.get(eps[0].base_url, {})
        print()
        print("  " + grey("An endpoint is a server Pragma can talk to, under a name"))
        print("  " + grey("you choose. There are none yet, so `add` is the way in."))
        print()
        # WHERE THAT ADDRESS COMES FROM, said exactly. It used to say "the one
        # in .env" in both cases, which on a machine with no .env named a file
        # that is not there and made a built-in fallback look like a setting
        # somebody had written.
        if config_base_url():
            print("  " + grey("Meanwhile it talks to the address in .env:"))
        else:
            print("  " + grey("Meanwhile it tries llama.cpp's own default port,"))
            print("  " + grey("which is a guess, not a setting:"))
        print()
        print(f"    {eps[0].base_url}  {ok_bad(p.get('up'))}{endpoints.status_text(p)}{off()}")
    dim = GREY if accent() else ""
    for ep in (eps if cat["endpoints"] else []):
        p = found.get(ep.base_url, {})
        entry = cat["endpoints"][ep.name]
        extra = []
        if entry.get("key_env"):
            extra.append(f"key from ${entry['key_env']}")
        elif ep.api_key:
            extra.append("key set")
        if ep.model:
            extra.append(f"asks for {ep.model}")
        tail = f"  ({', '.join(extra)})" if extra else ""
        # Three lines under the name, each wrapped under itself: what answers
        # there, where it is, what it is.
        put(ep.name, roles_of(cat, ep.name) or "no role",
            wrapped(endpoints.status_text(p), ok_bad(p.get("up")))
            + wrapped(endpoints.short_url(ep.base_url) + tail, dim)
            + wrapped(nature(entry), dim),
            ("endpoint", ep.name))
        put()
    # A switch says what it IS, not what pressing it does: a menu where some
    # rows are verbs and one is a promise is a menu you have to read twice.
    # Enter flips it.
    opts = cat.get("options") or {}
    for name, blurb, _handler in ACTIONS:
        if name == "meaning":
            where = str((cat.get("embedding") or {}).get("url") or "")
            put(f"{name:<12}{endpoints.short_url(where) if where else 'off'}", blurb,
                means=("action", name))
        elif name in OPTION_BLURB:
            put(f"{name:<12}{'on' if opts.get(name) else 'off'}", OPTION_BLURB[name],
                means=("action", name))
        else:
            put(name, blurb, means=("action", name))
            put()
    i = pick("", options, notes, what.index(at) if at in what else 0, under=under)
    return None if i is None else what[i]


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


# -- what a model is, and the numbers it sends --------------------------------

def edit_row(entry: dict, kind: str, work: str, name: str = "") -> None:
    """One row of the table, knob by knob. Enter keeps, `-` hands it back."""
    table = entry.setdefault("sampling", {}).setdefault(kind, {})
    row = dict(table.get(work) or {})
    step(f"{name} > sampling > {kind} . {work}" if name
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
        step(f"{name} > sampling > advanced" if name else "sampling > advanced")
        rows, labels, notes = [], [], []
        for kind in endpoints.KINDS:
            for work in endpoints.FLAVOURS:
                rows.append((kind, work))
                labels.append(f"{kind} . {work}")
                sent = knob_text((entry.get("sampling", {}).get(kind) or {}).get(work) or {})
                notes.append(sent or "nothing: the server decides")
        i = pick("Which row?", labels, notes)
        if i is None:
            return
        edit_row(entry, *rows[i], name=name)


# -- asking the model about itself --------------------------------------------

def fetch(url: str, timeout: int = 30) -> str:
    """A page, through Pragma's own web_fetch.

    Pragma's, not a second HTTP client written here: the skill already has the
    timeout, the user agent and the error strings, and a page fetched two
    different ways is two things to keep in step. Nothing else of Pragma is
    used - no memory, no recall, no episode. This is a GET and a model reading
    what came back.

    Returns "" on anything that went wrong, since web_fetch reports failures
    as text beginning with ERROR / HTTP ERROR / TIMEOUT.
    """
    try:
        from skills.web_fetch.skill import web_fetch
    except Exception:
        return ""
    body = web_fetch(url, timeout=timeout, max_chars=400_000)
    if not body or body.startswith(("ERROR", "HTTP ERROR", "CONNECTION ERROR", "TIMEOUT")):
        return ""
    return body


def served_alias(ep) -> str:
    """The repository name the server was started from, when it says.

    llama.cpp answers /props with `model_alias`, which for a GGUF started by
    name is the HuggingFace path - "unsloth/Qwen3.6-35B-A3B-MTP-GGUF:UD-Q5_K_M".
    That is the only place the ORIGINAL name survives: /models reports the
    file, and a file name has had the org taken off it.
    """
    root = ep.base_url[:-3] if ep.base_url.endswith("/v1") else ep.base_url
    try:
        request = urllib.request.Request(root.rstrip("/") + "/props",
                                         headers={"User-Agent": "pragma/configure"})
        with urllib.request.urlopen(request, timeout=5) as answer:
            props = json.loads(answer.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    for key in ("model_alias", "model_path", "model"):
        value = str(props.get(key) or "")
        if "/" in value.replace("\\", "/"):
            return value
    return ""


def repositories(alias: str) -> list[str]:
    """The pages worth reading for this model, best first.

    A server is started from a QUANTISATION - `unsloth/Qwen3.6-35B-A3B-GGUF` -
    and whether that repository carries the original's card is up to whoever
    published it. The original is the authority, and HuggingFace will say
    which it is: the model API answers with `base_model`, so the link is read
    rather than guessed from the name.
    """
    repo = alias.replace("\\", "/").split(":")[0].strip("/")
    parts = [p for p in repo.split("/") if p]
    if len(parts) < 2:
        return []
    repo = "/".join(parts[-2:])
    out = []
    try:
        request = urllib.request.Request(f"https://huggingface.co/api/models/{repo}",
                                         headers={"User-Agent": "pragma/configure"})
        with urllib.request.urlopen(request, timeout=15) as answer:
            meta = json.loads(answer.read().decode("utf-8", "replace"))
        base = (meta.get("cardData") or {}).get("base_model")
        if isinstance(base, str):
            base = [base]
        for candidate in (base or []):
            if isinstance(candidate, str) and candidate.count("/") == 1:
                out.append(candidate)
    except Exception:
        pass
    out.append(repo)
    # Last resort when the API said nothing: the name without its quantisation
    # suffix is often the original.
    bare = re.sub(r"[-_.]?(gguf|mlx|awq|gptq)$", "", repo, flags=re.I)
    if bare != repo:
        out.append(bare)
    seen, unique = set(), []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


# The whole heading line, not its first character: the conventional heading is
# most of the evidence, so it has to be readable when it is scored.
_HEADING = re.compile(r"(?m)^#{1,4}[ \t]+\S[^\n]*")
# A SETTING, not a mention: `temperature=1.0` is advice, the word "temperature"
# in a sentence is not, and telling them apart is most of the work here.
_ASSIGNMENT = re.compile(
    r"(?i)\b(temperature|temp|top_p|top_k|min_p|presence_penalty|"
    r"frequency_penalty|repetition_penalty|repeat_penalty)\b\s*[=:]\s*-?[0-9]*\.?[0-9]+")
_KNOB_WORDS = re.compile(
    r"(?i)\b(temperature|temp|top_p|top_k|min_p|presence_penalty|"
    r"repetition_penalty|repeat_penalty)\b")


def _sections(page: str) -> list[tuple[int, int, str]]:
    """(start, end, heading) for every heading in a markdown card."""
    marks = [(m.start(), m.group(0).strip()) for m in _HEADING.finditer(page)]
    out = []
    for i, (start, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(page)
        out.append((start, end, heading))
    return out


def _score(text: str, heading: str) -> int:
    """How likely this passage is to BE the recommendation.

    Counting assignments rather than mentions: `temperature=1.0` is a setting,
    the word "temperature" in a sentence is not. The heading is worth a lot
    because cards are conventional about it, and "bench" is worth losing
    points over because a benchmark table's footnote is full of assignments
    that are a record of one leaderboard run, not advice.
    """
    score = 3 * len(_ASSIGNMENT.findall(text))
    low = heading.lower()
    if re.search(r"best practice|recommend|sampling parameter|generation config", low):
        score += 40
    elif re.search(r"\bsampling\b|\busage\b|\bparameters\b|how to use", low):
        score += 8
    if re.search(r"(?i)bench|leaderboard|evaluat", text[:2000]):
        score -= 25
    return score


def recommendations(page: str, budget: int = 9000) -> str:
    """The part of a model card that talks about sampling.

    WHY NOT JUST THE FIRST N CHARACTERS. Because that was the bug. On the card
    this was built against, the four recommended rows sit at character 64 439
    of 67 520 - at 95% of the page, under "Best Practices", below every
    benchmark table. A prefix of 24 000 characters contained NONE of them, and
    the only numbers it did contain were the footnotes of the benchmark tables
    ("temp=1.0, top_p=0.95, 200K context window" - what one leaderboard run
    used, not what the authors advise). The model was not reading the card
    badly; it was reading a part of the card that does not say what it was
    asked.

    WHY NOT THE FIRST MATCHING SECTION EITHER. Because that was the second
    bug. Taking sections in the order they appear spent the whole budget on a
    passage about VIDEO FRAME sampling, which is earlier and shares a word.
    Position is not evidence. So each section is SCORED - how many settings it
    actually assigns, whether its heading is the conventional one, whether it
    reads like a benchmark note - and the best ones are kept, then put back in
    document order so the page still reads like a page.
    """
    if not page:
        return ""
    ranked = []
    for start, end, heading in _sections(page):
        body = page[start:end]
        if not _ASSIGNMENT.search(body):
            continue
        # A section can be a whole deployment guide; keep the neighbourhood of
        # its settings rather than the guide.
        if end - start > 5000:
            first = _ASSIGNMENT.search(body)
            last = None
            for last in _ASSIGNMENT.finditer(body):
                pass
            lo = max(0, first.start() - 1200)
            hi = min(len(body), (last.end() if last else first.end()) + 800)
            body = body[:300] + "\n[...]\n" + body[lo:hi]
        ranked.append((_score(body, heading), start, body))
    if not ranked:
        return page[:budget]
    ranked.sort(key=lambda r: -r[0])
    # Relative to the best, not to zero. A section that merely mentions a knob
    # in passing - a note about VIDEO FRAME sampling, say - scores above zero
    # and would be carried along on budget alone, diluting the passage that
    # actually answers. The best section is always kept; the rest have to be
    # in its league.
    floor = max(1, ranked[0][0] // 4)
    kept, spent = [], 0
    for score, start, body in ranked:
        if kept and score < floor:
            break
        if spent + len(body) > budget:
            body = body[: max(0, budget - spent)]
        if not body:
            break
        kept.append((start, body))
        spent += len(body)
    kept.sort()
    return "\n\n[...]\n\n".join(body for _, body in kept)


_MODE_WORDS = re.compile(r"(?i)non[- ]?thinking|instruct|thinking|reasoning")
_CODING_WORDS = re.compile(r"(?i)cod(e|ing)|webdev|web dev|programm|software")
_SPELLING = {"temp": "temperature", "repetition_penalty": "repeat_penalty"}


def _knobs_in(line: str) -> dict:
    """Every `name=number` on one line, under the names Pragma sends."""
    out = {}
    for m in _ASSIGNMENT.finditer(line):
        name = _SPELLING.get(m.group(1).lower(), m.group(1).lower())
        if name not in endpoints.KNOBS:
            continue
        try:
            value = float(m.group(0).rsplit("=", 1)[-1].rsplit(":", 1)[-1].strip())
        except ValueError:
            continue
        if name == "repeat_penalty" and value == 1.0:
            continue                    # 1.0 IS no penalty; sending it says nothing
        out[name] = value
    return out


def read_rows(text: str) -> dict:
    """The four rows, read off the page by this program rather than by a model.

    Cards are conventional about this, and the convention is machine-readable:

        - **Thinking mode for general tasks**:
          `temperature=1.0`, `top_p=0.95`, `top_k=20`, `presence_penalty=1.5`
        - **Instruct (or non-thinking) mode**:
          `temperature=0.7`, `top_p=0.80`, `top_k=20`, `presence_penalty=1.5`

    A label that names a mode, and the numbers beside it or on the next line.
    So they are taken directly. The model is the FALLBACK now, for cards that
    do not write it this way - which is the right way round: reading a table
    is not a job that needs judgement, and the one time it was given to a
    model it reported itself as instruct (it had just been told not to think)
    and filled only half the table.

    First match wins for a given row: a card that gives "instruct mode for
    general tasks" and later "instruct mode for reasoning tasks" means the
    first by that name, and the second is a case this shape has no box for.
    """
    rows: dict = {}
    lines = [ln for ln in (text or "").splitlines()]
    for i, line in enumerate(lines):
        knobs = _knobs_in(line)
        if len(knobs) < 2:
            continue                    # one stray number is not a recommendation
        # The label is on this line, or on the nearest non-empty one above it:
        # cards routinely put the name on one line and the numbers under it.
        label = line
        if not _MODE_WORDS.search(label):
            for back in range(i - 1, max(-1, i - 3), -1):
                if lines[back].strip():
                    label = lines[back]
                    break
        low = label.lower()
        if re.search(r"(?i)non[- ]?thinking|instruct", low):
            mode = "instruct"
        elif "thinking" in low:
            mode = "thinking"
        else:
            continue                    # a set of numbers belonging to nothing named
        task = "coding" if _CODING_WORDS.search(low) else "general"
        rows.setdefault(mode, {}).setdefault(task, knobs)
    return rows


def card(alias: str) -> tuple[str, str]:
    """(where it was read, the part of it that talks about sampling)."""
    for repo in repositories(alias):
        url = f"https://huggingface.co/{repo}/raw/main/README.md"
        page = fetch(url)
        if not page.strip():
            continue
        distilled = recommendations(page)
        # A card with no sampling section at all is not worth handing over:
        # the next repository in the list may be the one that has it.
        if _KNOB_WORDS.search(distilled):
            return url, distilled
    return "", ""


ASK_THE_MODEL = """You are running on a server, and someone is setting up a client for you.

Below is the part of your own model card that talks about sampling, and a
first reading of it made by a simple text scanner. The scanner only knows one
layout - a label naming a mode, with the numbers beside it - so on this card it
may be incomplete, or wrong, or empty.

YOUR JOB IS TO CHECK IT AGAINST THE CARD and answer with the corrected table.
Take your time: read the card first, then the reading, then decide. Where the
scanner is right, keep its numbers. Where the card says something else, or
says something the scanner missed, correct it.

Answer with one JSON object and nothing else after it:

{"kind": "thinking" or "instruct",
 "thinking": {"general": {}, "coding": {}},
 "instruct": {"general": {}, "coding": {}}}

"kind" is what the CARD says, not how you are running right now: "thinking" if
it describes a thinking or reasoning mode for this model, "instruct" if it does
not. Each inner object may set only these, all numbers:
  temperature, top_p, top_k, min_p, presence_penalty, repeat_penalty

RULES, and they matter more than filling the shape:
- Only numbers the card gives as a RECOMMENDATION. Numbers quoted beside a
  benchmark result - the settings a leaderboard run used - are not that.
- The card usually splits its advice the same way this shape does: thinking
  versus non-thinking (instruct), and general versus coding. Put each set where
  it belongs. A card may use other words for the same split.
- If the card separates thinking from instruct but says nothing about coding,
  put the SAME numbers in "general" and in "coding" for that mode.
- If the card names `repetition_penalty`, write it as `repeat_penalty`.
- Leave a setting out when it is not named. Leave a whole object empty only
  when the card offers nothing for that mode at all.
- Do not convert, do not average, do not invent a number that looks sensible.

The model is: {alias}

--- what the scanner read ---
{scanned}

--- the card ---
{card}
"""


def complete(table: dict) -> dict:
    """The proposed rows, finished the way the catalogue wants them.

    A card that separates thinking from instruct and says nothing about coding
    is the common case, and it means "the same numbers" - so the general row
    is copied across rather than left empty. Reading it over the general row
    at call time would give the same answer, but a page showing `coding:
    nothing` reads as a gap, and a file that states what it sends is a file
    you can check.

    A penalty of 1.0 is NO penalty, so it is dropped rather than sent: fewer
    fields in the request, and nothing to misread later as a decision. Cards
    write `repetition_penalty=1.0` precisely to say "leave this alone".
    """
    out = {}
    for kind, rows in (table or {}).items():
        clean_rows = {}
        for work, knobs in (rows or {}).items():
            knobs = {k: v for k, v in knobs.items()
                     if not (k == "repeat_penalty" and v == 1.0)}
            if knobs:
                clean_rows[work] = knobs
        if clean_rows.get("general") and not clean_rows.get("coding"):
            clean_rows["coding"] = dict(clean_rows["general"])
        if clean_rows:
            out[kind] = clean_rows
    return out


def _model_reads(ep, alias: str, text: str, where: str, scanned: dict):
    """Hand the page and the scanner's draft to the model, and read its answer.

    Returns (table, kind, True), or (None, "", False) when the answer could
    not be used - having said why, but without stopping: whether there is
    still something to offer is the caller's question.
    """
    draft = json.dumps(scanned, indent=1) if scanned else "(it found nothing)"
    prompt = (ASK_THE_MODEL.replace("{alias}", alias)
              .replace("{scanned}", draft).replace("{card}", text))
    payload = {
        "model": ep.model or "",
        "messages": [{"role": "user", "content": prompt}],
        # LET IT THINK, and give it room. Checking a reading against a page is
        # exactly the work reasoning is for, and this happens once when an
        # endpoint is set up - a minute here is cheap.
        #
        # It was off for a while, after a run where the whole 2 000-token
        # budget went into the <think> block and the content came back EMPTY.
        # The budget was the bug, not the thinking: 16 000 leaves room for
        # both, and a reply that still runs out says so by its finish_reason.
        #
        # response_format is NOT sent with it. A json_object grammar forces `{`
        # from the first token while the template is opening a thinking block,
        # and the two constrain each other into nothing. The object is found in
        # the reply instead - which the parser below has always done anyway,
        # because a model that adds a sentence around its JSON is not an error
        # worth failing on.
        "max_tokens": 16000,
        "chat_template_kwargs": {"enable_thinking": True, "thinking": True},
    }
    if not payload["model"]:
        payload.pop("model")
    headers = {"Content-Type": "application/json"}
    if ep.api_key:
        headers["Authorization"] = f"Bearer {ep.api_key}"
    reply, reasoned, why = {}, "", ""
    try:
        request = urllib.request.Request(
            ep.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"), headers=headers)
        with waiting("the model is reading it"):
            with urllib.request.urlopen(request, timeout=300) as answer:
                body = json.loads(answer.read().decode("utf-8", "replace"))
        choice = (body.get("choices") or [{}])[0]
        reply = choice.get("message") or {}
        why = str(choice.get("finish_reason") or "")
    except Exception as e:
        say(f"  The endpoint did not answer: {e}", "warn")
        return None, "", False
    said = (reply.get("content") or "").strip()
    reasoned = (reply.get("reasoning_content") or "").strip()
    if not said and reasoned:
        # A server that refused chat_template_kwargs thought anyway. The JSON
        # is often there, at the end of the reasoning - worth taking rather
        # than failing for a reason the operator cannot act on.
        said = reasoned
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
    table = complete(table)
    kind = proposed.get("kind") if proposed.get("kind") in endpoints.KINDS else ""
    if not table and not kind:
        # WHY it failed, not just THAT it did. `length` is the one the
        # operator can act on: the reply was cut off, so nothing was wrong
        # with the card or the page.
        if why == "length":
            say("  It ran out of output budget before finishing its answer.", "warn")
            print("  " + grey("A model that cannot be told to stop reasoning does this."))
            print("  " + grey("Set the numbers with `advanced` instead - they are on the"))
            print("  " + grey("page this just read: " + (where or "its model card") + "."))
        elif not said:
            say("  It answered with nothing at all.", "warn")
            print("  " + grey(f"finish_reason: {why or 'not reported'}"))
        else:
            say("  It answered, but not with numbers this page can use:", "warn")
            print("    " + grey(" ".join(said.split())[:300]))
        return None, "", False
    return table, kind, True


def ask_the_model(ep, entry: dict, name: str = "") -> bool:
    """Let the endpoint read its own card and propose the four rows."""
    step(f"{name} > sampling > ask it" if name else "sampling > ask it")
    print()
    with waiting("asking the server what it is serving"):
        alias = served_alias(ep)
    if not alias:
        say("  The server does not say which repository it was started from.", "warn")
        print("  " + grey("llama.cpp reports it in /props as model_alias; a model"))
        print("  " + grey("started from a plain file path has no name left to look up."))
        ask("", hint="enter to go back")
        return False
    say(f"  {alias}", "dim")
    with waiting("finding and reading its page on HuggingFace"):
        where, text = card(alias)
    if not text:
        say("  That page could not be read - no network, or it is not public.", "warn")
        ask("", hint="enter to go back")
        return False
    say(f"  {where}", "dim")
    say(f"  the sampling part of it is {len(text)} characters", "dim")

    # READ IT HERE FIRST, then have the model check that reading against the
    # page. The scanner knows ONE layout - a label naming a mode, numbers
    # beside it - and that layout is a convention, not a standard: the next
    # model's card may be written some other way, and a scanner that quietly
    # returns half a table is worse than one that returns none. So it is a
    # draft, not an answer. Checking a draft is also a much easier job than
    # extracting from scratch, which is the one the model was failing at.
    scanned = complete(read_rows(text))
    table, kind, by_model = _model_reads(ep, alias, text, where, scanned)
    if table is None:
        if not scanned:
            ask("", hint="enter to go back")
            return False
        print()
        say("  Falling back to what this program read off the page.", "dim")
        # The endpoint could not be asked, but the page was read. Offer that
        # rather than nothing, and say which it is.
        table, kind, by_model = scanned, ("thinking" if scanned.get("thinking")
                                          else "instruct"), False

    step(f"{name} > sampling > ask it" if name else "sampling > ask it")
    print()
    # WHICH ROUTE produced these, and whether the two agreed. Two readings
    # that match is the strongest thing this page can say; one that was
    # corrected is worth looking at twice, and a reading with nothing behind
    # it is worth saying so about.
    if not by_model:
        headline = "Read off its card, by this program alone:"
    elif table == scanned and scanned:
        headline = "Read off its card, and the model agrees:"
    elif scanned:
        headline = "Read off its card, corrected by the model:"
    else:
        headline = "The model read this off its card:"
    say(f"  {headline}", "accent")
    print()
    if kind:
        print(f"    a {kind} model")
    for half in endpoints.KINDS:
        for work in endpoints.FLAVOURS:
            sent = knob_text((table.get(half) or {}).get(work) or {})
            was = knob_text((scanned.get(half) or {}).get(work) or {})
            mark = "  " + grey(f"(was: {was or 'nothing'})") if (
                by_model and scanned and sent != was) else ""
            print(f"    {half} . {work:<8} " + (sent or grey("nothing")) + mark)
    print()
    if not by_model:
        print("  " + grey("The endpoint could not be asked, so nothing checked this."))
        print("  " + grey("It reads one common layout; a card written another way"))
        print("  " + grey("gives half a table or none. Look before you say yes."))
    else:
        print("  " + grey("Two readings of the same page: this program's, and the"))
        print("  " + grey("model's check of it. Neither is authority - what a card"))
        print("  " + grey("recommends is not always what you want. Look before you say yes."))
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

def reasons_text(entry: dict) -> str:
    """Who reasons on this endpoint, as one line - or "" if nothing can."""
    if entry.get("kind") != "thinking":
        return ""
    on = [r for r in endpoints.ROLES if endpoints.reasons_for(entry, r)]
    if len(on) == len(endpoints.ROLES):
        return "all of them"
    return ", ".join(on) if on else "nobody"


def who_reasons(entry: dict, name: str) -> bool:
    """One switch per role. Written only when they differ from the
    default - the agent and the memory reason, the recall answers at once -
    so an endpoint that takes the default has no `reasons` key at all.
    """
    changed = False
    # WHERE THE CURSOR IS WHEN THE PAGE COMES BACK. A switch is flipped by
    # pressing Enter on it, and the page redraws to show the new answer - so
    # landing back on the first row means the one you are working on walks
    # away from you every time you press it. It stays where you left it.
    at = 0
    while True:
        step(f"{name} > who reasons")
        print()
        print("  " + grey("This model reasons. Each role can be asked"))
        print("  " + grey("to use it, or to answer at once instead."))
        rows = [f"{role:<8}{'reasons' if endpoints.reasons_for(entry, role) else 'answers at once'}"
                for role in endpoints.ROLES]
        i = pick("", rows, [REASONS_BLURB[r] for r in endpoints.ROLES], at)
        if i is None:
            return changed
        at = i
        role = endpoints.ROLES[i]
        now = {r: endpoints.reasons_for(entry, r) for r in endpoints.ROLES}
        now[role] = not now[role]
        # Written only when it differs from what an endpoint that says nothing
        # gets - which is no longer "all three": the recall answers at once
        # by default. Compared against "all true", turning the recall ON would
        # have removed the table and switched it straight back off.
        if now == {r: endpoints._REASONS_BY_DEFAULT[r] for r in endpoints.ROLES}:
            entry.pop("reasons", None)
        else:
            entry["reasons"] = now
        changed = True


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
    state["note"] = (f"{name} added - the first endpoint, so every role uses it"
                     if first else f"{name} added - it serves nothing until a role is given to it")
    # Its own page is where it goes next: what it is has not been said yet.
    state["open"] = name
    return True


def ask_serves(state: dict, name: str) -> bool:
    """The four roles and who answers each: Enter gives one to this endpoint.

    It asked "what should it serve?" over a list of the roles alone, so the
    answer was given without seeing what it took the role away from.
    """
    cat = state["cat"]
    changed = False
    at = 0
    while True:
        step(f"{name} > serves")
        print()
        print("  " + grey(f"Who answers each role now. Enter gives it to {name};"))
        print("  " + grey("to take one away, give it to another endpoint from its page."))
        rows = ["everything"] + [f"{role:<8}{role_target(cat, role)[0]}" for role in endpoints.ROLES]
        i = pick("", rows, ["every role - what most setups are"]
                 + [ROLE_BLURB[r] for r in endpoints.ROLES], at)
        if i is None:
            return changed
        at = i
        for role in (endpoints.ROLES if i == 0 else (endpoints.ROLES[i - 1],)):
            if cat["roles"].get(role) != name:
                cat["roles"][role] = name
                changed = True


def ask_kind(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    step(f"{name} > what it is")
    got = choose("Does this model reason before it answers?",
                 [(k, KIND_BLURB[k]) for k in endpoints.KINDS], entry.get("kind", ""))
    if not got:
        return False
    entry["kind"] = got
    return True


def ask_work(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    step(f"{name} > what it is for")
    got = choose("What is this endpoint used for?",
                 [(w, WORK_BLURB[w]) for w in endpoints.FLAVOURS], entry.get("work", "general"))
    if not got:
        return False
    entry["work"] = got
    return True


def ask_who(state: dict, name: str) -> bool:
    return who_reasons(state["cat"]["endpoints"][name], name)


def ask_sampling(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    step(f"{name} > sampling")
    how = choose("How should it be sampled?", [
        ("standard", "send nothing: the server keeps what it was started with"),
        ("advanced", "type the numbers yourself, row by row"),
        ("ask it",   "the model reads its own card on HuggingFace and fills them in"),
    ])
    if how == "standard":
        entry.pop("sampling", None)
        return True
    if how == "advanced":
        advanced(entry, name)
        return True
    if how == "ask it":
        return ask_the_model(endpoints.from_entry(name, entry), entry, name)
    return False


def ask_name(state: dict, name: str) -> bool:
    cat = state["cat"]
    step(f"{name} > name")
    print()
    print("  " + grey("What these pages call the server. Every role that uses it"))
    print("  " + grey("follows the new name."))
    print()
    new = ask("Name", name)
    if new is None or new == name:
        return False
    rename(cat, name, new)
    state["renamed"] = new
    return True


def ask_address(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    step(f"{name} > address")
    print()
    url = ask("Address", entry.get("url", ""), hint="/v1 is added if missing")
    if url is None:
        return False
    url = normalise_url(url)
    if url == entry.get("url"):
        return False
    entry["url"] = url
    state.pop("answers", None)        # the page it goes back to asks the new one
    return True


def ask_model(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    step(f"{name} > model")
    print()
    print("  " + grey("Only for a server that hosts several models: the one to ask"))
    print("  " + grey("it for. Left empty, it answers with whatever it is serving."))
    print()
    now = entry.get("model", "")
    model = ask("Model name", now, hint="`-` clears it" if now else "[whatever the server serves]")
    if model is None:
        return False
    model = "" if model.strip() == "-" else model.strip()
    if model == now:
        return False
    if model:
        entry["model"] = model
    else:
        entry.pop("model", None)
    state.pop("answers", None)
    return True


def ask_key(state: dict, name: str) -> bool:
    entry = state["cat"]["endpoints"][name]
    before = (entry.get("key_env", ""), entry.get("key", ""))
    step(f"{name} > API key")
    print()
    print("  " + grey("A local server needs none. For one that does, the key is better"))
    print("  " + grey("left in an environment variable whose NAME is given here: the"))
    print("  " + grey("key itself is then never written to a file."))
    print()
    key_env = ask("Environment variable holding the key", before[0],
                  hint="its name, or `-` to clear" if before[0] else "[none] - its name")
    if key_env is None:
        return False
    key_env = key_env.strip().lstrip("$")
    if key_env.strip("-"):
        entry["key_env"] = key_env
        entry.pop("key", None)
    else:
        entry.pop("key_env", None)
        import getpass
        # ctrl+D here leaves by the door that puts the endpoint back as it was.
        typed = getpass.getpass("  API key (enter keeps what is set, `-` clears): ").strip()
        if typed == "-":
            entry.pop("key", None)
        elif typed:
            entry["key"] = typed
    if (entry.get("key_env", ""), entry.get("key", "")) == before:
        return False
    state.pop("answers", None)
    return True


def ask_remove(state: dict, name: str) -> bool:
    cat = state["cat"]
    users = [role for role, n in cat["roles"].items() if n == name]
    if users and len(cat["endpoints"]) > 1:
        raise ValueError(f"'{name}' serves {', '.join(users)} - open the endpoint that should "
                         f"take {'it' if len(users) == 1 else 'them'} over, and say so under `serves`")
    step(f"{name} > remove")
    print()
    print("  " + grey(cat["endpoints"][name].get("url", "")))
    if not confirm(f"Remove '{name}'?", f"yes, remove {name}"):
        return False
    del cat["endpoints"][name]
    cat["roles"] = {r: n for r, n in cat["roles"].items() if n != name}
    state["note"] = (f"{name} removed" if cat["endpoints"]
                     else "no endpoints left: Pragma goes back to the one in .env")
    return True


# What can be asked about ONE endpoint, in the order its page asks it. Every
# row is one question, and says its answer beside its name. They were three
# pages - use, tune, edit - reached by choosing the verb first and the
# endpoint second; and `edit` asked its four questions in a row, whichever of
# them you had come to change.
ENDPOINT_ROWS = [
    ("serves",         "the roles that ask this server", ask_serves),
    ("what it is",     "a reasoning model, or one that answers at once", ask_kind),
    ("what it is for", "conversation, or writing code", ask_work),
    ("who reasons",    "each role, on or off", ask_who),
    ("sampling",       "the knobs every request carries", ask_sampling),
    ("name",           "what these pages call it", ask_name),
    ("address",        "where the server listens", ask_address),
    ("model",          "which one, where a server hosts several", ask_model),
    ("API key",        "typed, or left in an environment variable", ask_key),
    ("remove",         "take it off the list", ask_remove),
]
_GAP_BEFORE = ("name", "remove")


def endpoint_page(state: dict, name: str) -> bool:
    """One endpoint: what answers there, and one row for everything about it."""
    changed = False
    at = None
    while True:
        cat = state["cat"]
        if name not in cat["endpoints"]:
            return changed
        entry = cat["endpoints"][name]
        step(name)
        eps = [endpoints.from_entry(n, e) for n, e in cat["endpoints"].items()]
        p = answers(state, eps).get(endpoints.from_entry(name, entry).base_url, {})
        print()
        for line in wrapped(endpoints.status_text(p), ok_bad(p.get("up")), indent=2):
            print("  " + line)
        told = state.pop("note", "")
        if told:
            print()
            say(f"  {told}", "good")
        says = {
            "serves": roles_of(cat, name) or "no role",
            "what it is": entry.get("kind") or "not set",
            "what it is for": entry.get("work") or "general",
            "who reasons": reasons_text(entry),
            "sampling": ("the server's own numbers" if not entry.get("sampling")
                         else knob_text(endpoints.sampling_row(entry)) or "nothing set yet"),
            "name": name,
            "address": endpoints.short_url(entry.get("url", "")),
            "model": entry.get("model") or "the server's own",
            "API key": key_text(entry),
            "remove": "",
        }
        # Only what can change something. With one endpoint there is nobody
        # else to serve a role; on a model that answers at once there is no
        # reasoning to switch. A row that cannot change anything is a row that
        # has to be explained.
        absent = set()
        if len(cat["endpoints"]) < 2:
            absent.add("serves")
        if entry.get("kind") != "thinking":
            absent.add("who reasons")
        options, notes, what = [], [], []
        for label, blurb, handler in ENDPOINT_ROWS:
            if label in absent:
                continue
            if label in _GAP_BEFORE:
                options.append("")
                notes.append("")
                what.append(None)
            options.append(f"{label:<16}{says[label]}".rstrip())
            notes.append(blurb)
            what.append((label, handler))
        labels = [w[0] if w else None for w in what]
        # The cursor comes back to the row it left: a page that redraws with
        # the first row under the cursor walks away from what you were doing.
        i = pick("", options, notes, labels.index(at) if (at and at in labels) else 0)
        if i is None:
            return changed
        at, handler = what[i]
        if run_action(state, lambda st, h=handler, n=name: h(st, n)):
            changed = True
            name = state.pop("renamed", name)


def _flip(state: dict, key: str) -> bool:
    """One press, on or off. No page of its own: it is one answer."""
    cat = state["cat"]
    opts = dict(cat.get("options") or {})
    if opts.get(key, False):
        opts.pop(key, None)              # off is the default: say nothing
    else:
        opts[key] = True
    if opts:
        cat["options"] = opts
    else:
        cat.pop("options", None)
    return True


def cmd_prediction(state: dict) -> bool:
    return _flip(state, "prediction")


def cmd_critic(state: dict) -> bool:
    return _flip(state, "critic")


def cmd_meaning(state: dict) -> bool:
    """The server that lets the memory be searched by meaning: its address, or none."""
    cat = state["cat"]
    now = str((cat.get("embedding") or {}).get("url") or "")
    step("meaning")
    print()
    print("  " + grey("Before a recall the memory is searched for what fits the request."))
    print("  " + grey("By default it goes by the words the two share. With an embedding"))
    print("  " + grey("server it goes by meaning: another wording, or another language,"))
    print("  " + grey("still finds the memory. It is a small model of its own, on its own"))
    print("  " + grey("port - not the one you talk to."))
    print()
    url = ask("Address of the embedding server", now,
              hint="e.g. 127.0.0.1:7190 - /v1 is added if missing; 'off' for none")
    if url is None:
        return False
    if url.strip().lower() in ("off", "none", "no", "-"):
        if not now:
            return False
        cat.pop("embedding", None)
        state["note"] = "the memory is searched by words"
        return True
    url = normalise_url(url)
    size, why = 0, ""
    try:
        import requests
        r = requests.post(url + "/embeddings", json={"model": "embedding", "input": ["hello"]}, timeout=15)
        r.raise_for_status()
        vector = r.json()["data"][0]["embedding"]
        if vector and isinstance(vector[0], list):
            vector = vector[0]
        size = len(vector)
    except Exception as e:
        why = f"{type(e).__name__}: {str(e)[:90]}"
    print(f"  {url}  {ok_bad(bool(size))}"
          + (f"answers with {size} numbers for a text" if size else f"does not answer as one - {why}")
          + off())
    if not size and not confirm("Keep this address anyway?", "yes, keep it"):
        return False
    if url == now:
        return False
    cat["embedding"] = dict(cat.get("embedding") or {}, url=url)
    state["note"] = ("the memory is searched by meaning, from the next turn"
                     if size else "kept - until it answers, the memory is searched by words")
    return True


# What each switch IS, beside its name - the row says it, not a page.
OPTION_BLURB = {
    "prediction": "the line you will probably type next, in grey; tab takes it",
    "critic":     "the work checked against your request before it is delivered",
}


# What the page offers under its endpoints: one more of them, and the
# switches that are the harness's rather than one server's.
ACTIONS = [
    ("add",       "a server: its address, its name, what it is", cmd_add),
    ("prediction", "", cmd_prediction),
    ("critic", "", cmd_critic),
    ("meaning", "the memory searched by meaning, with an embedding server", cmd_meaning),
]


def save(state: dict) -> None:
    """The file, or no file: an empty catalogue means "use .env", so it goes.

    Unless a harness switch has been set. Those live in the same file, and a
    file deleted for having no endpoints would take them with it - so turning
    prediction on before adding a server would forget it the moment the page
    redrew.
    """
    cat = state["cat"]
    path = endpoints.catalogue_path()
    if not cat.get("options"):
        cat.pop("options", None)      # never write an empty object
    if cat["endpoints"] or cat.get("options") or cat.get("embedding"):
        endpoints.save_catalogue(cat)
    elif path.exists():
        path.unlink()


def run_action(state: dict, handler) -> bool:
    """One command, with the catalogue put back if it went wrong.

    ctrl+D out of any question is a way back, not a failure, so it leaves no
    message: the page redraws and shows what is actually there.
    """
    cat = state["cat"]
    before = {"endpoints": json.loads(json.dumps(cat["endpoints"])),
              "roles": dict(cat["roles"]),
              "options": dict(cat.get("options") or {})}
    had = dict(cat["embedding"]) if cat.get("embedding") else None

    def put_back() -> None:
        cat.update(before)
        if had is None:
            cat.pop("embedding", None)
        else:
            cat["embedding"] = had

    try:
        if handler(state):
            save(state)
            return True
    except (EOFError, KeyboardInterrupt):
        put_back()
        state["note"] = ""
    except (ValueError, endpoints.EndpointError) as e:
        put_back()
        print()
        say(f"  {e}", "warn")
        ask("", hint="enter to go back")
    return False


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
    if (data or {}).get("options"):
        cat["options"] = dict(data["options"])
    if (data or {}).get("embedding"):
        cat["embedding"] = dict(data["embedding"])
    state = {"cat": cat}

    old = Path.home() / ".pragma" / "sampling.json"
    if old.is_file():
        state["note"] = (f"{old} is no longer read - sampling lives beside "
                         f"each endpoint now, on its own page")

    changed = False
    at: tuple = ()
    handlers = {name: handler for name, _blurb, handler in ACTIONS}
    while True:
        chosen = front(state, at)
        if chosen is None:
            clear()
            return CHANGED if changed else UNCHANGED
        at = chosen
        kind, name = chosen
        if kind == "endpoint":
            if endpoint_page(state, name):
                changed = True
            continue
        if run_action(state, handlers[name]):
            changed = True
        opened = state.pop("open", "")
        if opened in cat["endpoints"]:
            at = ("endpoint", opened)
            if endpoint_page(state, opened):
                changed = True


if __name__ == "__main__":
    sys.exit(main())
