# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# endpoints.py — which endpoint a call goes to, and what is known about each.
#
# Pragma can talk to several endpoints: the agent on one model, the curator
# and the memory faculties on others, possibly on other machines. Three things
# live here.
#
# ROUTING. A call's role comes from the faculty making it - the name every
# faculty already sets with llm_client.faculty(). CURATOR is `recall`; the
# faculties that write memory are `memory`; anything unlabelled is `agent`:
# the agent's own steps, the summariser, the forced verdict. No call site
# names an endpoint, so a faculty added later is routed by the same rule
# without remembering to ask.
#
# THE CATALOGUE. ~/.pragma/endpoints.json (or the file PRAGMA_ENDPOINTS names)
# lists the endpoints by name and assigns one to each role:
#
#     {
#       "endpoints": {
#         "big": {
#           "url": "http://127.0.0.1:8100/v1",
#           "kind": "thinking", "work": "general",
#           "sampling": {
#             "thinking": {"general": {"temperature": 0.6, "top_p": 0.95},
#                          "coding":  {"temperature": 0.2}},
#             "instruct": {"general": {}, "coding": {}}
#           }
#         },
#         "small": {"url": "http://127.0.0.1:8190/v1", "model": "",
#                   "key": "", "key_env": ""}
#       },
#       "roles": {"agent": "big", "recall": "small", "memory": "big"}
#     }
#
# ONE FILE. What a model is (thinking or instruct), what an endpoint is used
# for (general or coding) and the knobs each of those four combinations sends
# live in the entry, beside the address. They used to live in a second file,
# ~/.pragma/sampling.json, keyed by a model name that had to be spelled the
# way the server happened to report it - two files to keep in step, and a
# table that quietly did not apply when the spelling drifted. The endpoint is
# the thing that is really being described, so it holds the description.
#
# It is global rather than per project because the machines are the same
# whichever project is open, and it lives outside every backup, so no address
# or key ends up in a zip. A key is written either as "key" or, to keep it out
# of the file, as "key_env": the name of an environment variable holding it.
# The names are the operator's own: whatever reads well in /configure.
#
# ONE PLACE OR THE OTHER, never both. With no catalogue, every role uses the
# endpoint in .env (LLM_BASE_URL, LLM_API_KEY, DEFAULT_MODEL) exactly as
# before, which is what a machine that never opens /configure keeps doing.
# Once the catalogue exists it is the only place endpoints are read from:
# /configure moves the .env endpoint into it, under a name, on the first
# change, and LLM_BASE_URL is not read again while the file is there. Two
# sources side by side - one of them a nameless "default" living in another
# file - was a distinction every reader of the page had to have explained.
#
# A role the catalogue does not assign follows the agent; the agent must be
# assigned, unless the catalogue lists a single endpoint.
#
# A catalogue that cannot be followed - broken JSON, a role naming an endpoint
# that is not listed - is an error, never a quiet return to .env. Falling back
# would put a call on a model nobody chose and file its output under the wrong
# name. The faculties already survive a failed call: the curator has its
# deterministic fallback, and a consolidation job fails and can be retried.
#
# STATE. What used to be one value per process is one value per endpoint: the
# model it actually serves, and whether it turned out to reject tools or JSON
# schemas. Keyed by base URL, so two roles on the same server share what was
# learned about it, and pointing a role elsewhere starts clean.

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import config

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
ROLES = ("agent", "recall", "memory")

# WHAT A MODEL IS, AND WHAT IT IS FOR. Both are properties of the server, not
# of a project: the machine at the end of the address is running one model,
# started one way, and no project of ours changes that by opening. So the
# endpoint carries them, and every project that talks to it inherits them.
#
#   kind      thinking | instruct   what the model is
#   work      general  | coding     what this endpoint is used for
#   sampling  the four rows those two words index, each a set of knobs
#   reasons   which of the three roles actually reasons on it
#
# The knobs are the ones MEASURED to arrive (llama.cpp, 2026-09-21). There is
# no `repetition_penalty` in the list on purpose: that is the HuggingFace
# spelling and this server drops it in silence, so a table that carried it
# would be a number nobody sends.
KINDS = ("thinking", "instruct")
FLAVOURS = ("general", "coding")
KNOBS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty")

# SUMMARIZER is deliberately absent: it compresses the agent's own history, so
# it runs where the agent runs.
_ROLE_OF_FACULTY = {
    "CURATOR":        "recall",
    "SEGMENTER":      "memory",
    "CONSOLIDATOR":   "memory",
    "RECONSOLIDATOR": "memory",
    "ABSTRACTOR":     "memory",
    "REFLECT":        "memory",
    # What you might ask next is a recall question in everything but name: it
    # reads the turn that just ended and answers at once, under a schema. It
    # belongs where the curator is, on the role you are free to keep fast.
    "SUGGESTER":      "recall",
}


# WHO REASONS, ROLE BY ROLE. `kind` says whether the model CAN reason;
# `reasons` says which of the three roles is asked to. A model that reasons
# reasons for everyone unless this says otherwise, so an endpoint written
# before this existed behaves exactly as it did.
#
# It is not one switch because the three roles do different work, and the
# difference has been measured: on Qwen3.6 a curator picking fragments under a
# schema cost 83 completion tokens and 8.6s reasoning, and 17 tokens and 1.6s
# without, FOR THE SAME ANSWER. The curator runs on every turn, so that is the
# wait a person feels; an agent writing code and a reconsolidator revising a
# belief are the calls where deliberating earns its seconds.
#
# An instruct endpoint has nothing to switch, and answers False for everyone
# without consulting the table - which is why the table is kept rather than
# zeroed when `kind` changes: switching to instruct and back finds the same
# three answers, instead of three that nobody chose.
def reasons_for(entry: dict, role: str = "agent") -> bool:
    """Is `role` asked to reason on this endpoint?"""
    if (entry or {}).get("kind") != "thinking":
        return False
    table = (entry or {}).get("reasons")
    if not isinstance(table, dict):
        return True
    return bool(table.get(role if role in ROLES else "agent", True))


# WHAT THE HARNESS DOES, as opposed to what a model is. These sit beside the
# endpoints rather than in a project's settings because they are answered once
# for the machine: /configure is the page you open when you set Pragma up, and
# a switch that means the same thing in every project belongs on it.
#
#   prediction  three things you might ask next, under the empty prompt
OPTIONS = ("prediction",)


def option(name: str, default: bool = False) -> bool:
    """One harness-wide switch from the catalogue. Never raises."""
    try:
        data, error = load_catalogue()
        if error or not data:
            return default
        got = (data.get("options") or {}).get(name)
        return default if got is None else bool(got)
    except Exception:
        return default


class EndpointError(RuntimeError):
    """The catalogue says something that cannot be followed."""


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str          # OpenAI-compatible base, ending in /v1, no trailing slash
    api_key: str = ""
    model: str = ""        # the name to send; empty means whatever the server serves


@dataclass
class State:
    served_model: str = ""
    tools_unsupported: bool = False
    schema_unsupported: bool = False
    # chat_template_kwargs is llama.cpp's, not OpenAI's: a server that rejects
    # it is remembered, and the thinking switch is not sent to it again.
    template_unsupported: bool = False


_STATES: dict[str, State] = {}
_LOCK = threading.Lock()
_CATALOGUE: dict = {"stamp": None, "data": None, "error": ""}


def role_of(faculty: str) -> str:
    """The role a faculty's calls belong to; unlabelled calls are the agent's."""
    return _ROLE_OF_FACULTY.get((faculty or "").strip().upper(), "agent")


def catalogue_path() -> Path:
    raw = os.environ.get("PRAGMA_ENDPOINTS", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".pragma" / "endpoints.json"


def _sampling_problem(table) -> str:
    """What makes an endpoint's sampling table unusable, or ""."""
    if table is None:
        return ""
    if not isinstance(table, dict):
        return "\"sampling\" must be an object of thinking/instruct rows"
    for half, rows in table.items():
        if half not in KINDS:
            return f"\"sampling\" has \"{half}\"; it has {' and '.join(KINDS)}"
        if not isinstance(rows, dict):
            return f"\"sampling.{half}\" must be an object of general/coding rows"
        for flavour, knobs in rows.items():
            if flavour not in FLAVOURS:
                return f"\"sampling.{half}\" has \"{flavour}\"; it has {' and '.join(FLAVOURS)}"
            if not isinstance(knobs, dict):
                return f"\"sampling.{half}.{flavour}\" must be an object of numbers"
            for knob, value in knobs.items():
                if knob not in KNOBS:
                    return (f"\"sampling.{half}.{flavour}\" sets \"{knob}\", which is not sent"
                            f" - the knobs are {', '.join(KNOBS)}")
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return f"\"sampling.{half}.{flavour}.{knob}\" is not a number"
    return ""


def sampling_row(entry: dict, kind: str = "", work: str = "") -> dict:
    """The knobs one endpoint sends for one (kind, work), or {}.

    The coding row is read OVER the general one of its own half, so a table
    can say "the same, cooler" and mean it - naming one number must not
    silently drop the four beside it.
    """
    table = (entry or {}).get("sampling") or {}
    half = kind if kind in KINDS else (entry or {}).get("kind") or "instruct"
    flavour = work if work in FLAVOURS else (entry or {}).get("work") or "general"
    rows = table.get(half) or {}
    knobs = dict(rows.get("general") or {})
    if flavour != "general":
        knobs.update(rows.get(flavour) or {})
    return {k: float(v) for k, v in knobs.items() if k in KNOBS and v is not None}


def _reasons_problem(table) -> str:
    """What makes an endpoint's `reasons` unusable, or ""."""
    if table is None:
        return ""
    if not isinstance(table, dict):
        return "\"reasons\" must be an object of role switches"
    for role, on in table.items():
        if role not in ROLES:
            return f"\"reasons\" has \"{role}\"; the roles are {', '.join(ROLES)}"
        if not isinstance(on, bool):
            return f"\"reasons.{role}\" must be true or false"
    return ""


def _problem(data) -> str:
    """What makes a parsed catalogue unusable, or ""."""
    if not isinstance(data, dict):
        return "the top level must be an object with \"endpoints\" and \"roles\""
    eps = data.get("endpoints", {})
    roles = data.get("roles", {})
    if not isinstance(eps, dict) or not isinstance(roles, dict):
        return "\"endpoints\" and \"roles\" must both be objects"
    # A catalogue with no endpoints used to be meaningless, and saying so
    # caught a half-written file. It is not meaningless any more: the harness
    # switches live here too, and turning prediction on before adding a server
    # is a reasonable order to do things in. With no endpoints every role
    # falls back to .env, exactly as it does with no file at all.
    if not eps and not data.get("options"):
        return "it lists no endpoints"
    for name, e in eps.items():
        if not isinstance(e, dict) or not str(e.get("url") or "").strip():
            return f"endpoint \"{name}\" has no \"url\""
        if e.get("kind") and e["kind"] not in KINDS:
            return f"endpoint \"{name}\" is \"{e['kind']}\"; it is {' or '.join(KINDS)}"
        if e.get("work") and e["work"] not in FLAVOURS:
            return f"endpoint \"{name}\" works on \"{e['work']}\"; it is {' or '.join(FLAVOURS)}"
        bad = _sampling_problem(e.get("sampling"))
        if bad:
            return f"endpoint \"{name}\": {bad}"
        bad = _reasons_problem(e.get("reasons"))
        if bad:
            return f"endpoint \"{name}\": {bad}"
    for role, name in roles.items():
        if role not in ROLES:
            return f"\"{role}\" is not a role; the roles are {', '.join(ROLES)}"
        if name not in eps:
            return f"role \"{role}\" names \"{name}\", which is not in \"endpoints\""
    if not roles.get("agent") and len(eps) > 1:
        return "no endpoint is assigned to \"agent\", and there is more than one to choose from"
    opts = data.get("options")
    if opts is not None:
        if not isinstance(opts, dict):
            return "\"options\" must be an object of switches"
        for key, on in opts.items():
            if key not in OPTIONS:
                return f"\"options\" has \"{key}\"; it has {', '.join(OPTIONS)}"
            if not isinstance(on, bool):
                return f"\"options.{key}\" must be true or false"
    return ""


def load_catalogue() -> tuple[dict | None, str]:
    """(catalogue, error). No file is (None, ""): .env serves every role.

    Re-read whenever the file changes, so a catalogue edited by /configure
    applies to the next call without restarting anything.
    """
    path = catalogue_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        return None, ""
    except OSError as e:
        return None, f"{path}: {e}"
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _CATALOGUE["stamp"] == stamp:
            return _CATALOGUE["data"], _CATALOGUE["error"]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        error = _problem(data)
    except Exception as e:
        data, error = None, f"not valid JSON ({e})"
    if error:
        data, error = None, f"{path}: {error}"
    with _LOCK:
        _CATALOGUE.update(stamp=stamp, data=data, error=error)
    return data, error


def problem(data) -> str:
    """Why a catalogue cannot be followed, or "" when it can."""
    return _problem(data)


def _from_env() -> Endpoint:
    return Endpoint(
        name="default",
        base_url=(config.LLM_BASE_URL or DEFAULT_BASE_URL).rstrip("/"),
        api_key=config.LLM_API_KEY or "",
        model=config.DEFAULT_MODEL or "",
    )


def from_entry(name: str, entry: dict) -> Endpoint:
    """An Endpoint from one catalogue entry, with its key resolved."""
    key = str(entry.get("key") or "")
    if not key and entry.get("key_env"):
        key = os.environ.get(str(entry["key_env"]), "")
    return Endpoint(name=name, base_url=str(entry["url"]).strip().rstrip("/"),
                    api_key=key, model=str(entry.get("model") or ""))


def _named(data: dict, name: str) -> Endpoint:
    return from_entry(name, (data.get("endpoints") or {})[name])


def env_endpoint() -> Endpoint:
    """The endpoint in .env: what every role uses while there is no catalogue."""
    return _from_env()


def save_catalogue(data: dict) -> None:
    """Write the catalogue so a reader never sees half a file."""
    error = _problem(data)
    if error:
        raise EndpointError(error)
    path = catalogue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ── What is at an endpoint ────────────────────────────────────────────────────
# One answer for every page that shows an endpoint - the home prompt, the
# briefing, /configure - so they cannot disagree about the same server.

def model_name(raw: str) -> str:
    """"C:\\models\\Qwen3.8-27B.gguf" -> "Qwen3.8-27B", as ping_models reports it."""
    name = str(raw or "").replace("\\", "/").split("/")[-1]
    for ext in (".gguf", ".bin"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    return name


def probe(ep: Endpoint, timeout: float = 3.0) -> dict:
    """Ask an endpoint what it is, quickly. Never raises.

    Three different "down"s are told apart, because each has a different fix:
    nothing listening (start the server, or check the address), something
    that accepts the connection and closes it without a word (typically an SSH
    tunnel whose far end has no server), and something that answers but not
    as an OpenAI-compatible endpoint (a wrong port or path).
    """
    import http.client
    import urllib.error
    import urllib.request

    out = {"url": ep.base_url, "up": False, "served": "", "n_ctx": 0, "slots": 0, "error": ""}
    if not config.endpoint_reachable(ep.base_url):
        out["error"] = "not connected"
        return out

    def get(url):
        req = urllib.request.Request(url)
        if ep.api_key:
            req.add_header("Authorization", f"Bearer {ep.api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        data = get(ep.base_url + "/models")
    except urllib.error.HTTPError as e:
        out["error"] = f"answers HTTP {e.code} on /models - a wrong address or key?"
        return out
    except Exception as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            out["error"] = f"connected, but no answer within {timeout:g}s"
        elif isinstance(reason, (ConnectionError, http.client.RemoteDisconnected)):
            out["error"] = ("the connection is accepted and closed without an answer"
                            " - a tunnel with no server behind it?")
        else:
            out["error"] = "answers, but not as an OpenAI-compatible endpoint"
        return out
    out["up"] = True
    try:
        listed = data.get("data") or []
        out["served"] = model_name(listed[0].get("id", "")) if listed else ""
    except Exception:
        pass
    try:
        root = ep.base_url[:-3] if ep.base_url.endswith("/v1") else ep.base_url
        props = get(root.rstrip("/") + "/props")
        out["n_ctx"] = int((props.get("default_generation_settings") or {}).get("n_ctx") or 0)
        out["slots"] = int(props.get("total_slots") or 0)
    except Exception:
        pass                                    # /props is llama.cpp's, not required
    return out


def probe_all(eps: list[Endpoint], timeout: float = 3.0) -> dict[str, dict]:
    """probe() for several endpoints at once, each distinct URL asked once."""
    urls = {ep.base_url: ep for ep in eps}
    results: dict[str, dict] = {}
    threads = [threading.Thread(target=lambda e=e: results.__setitem__(e.base_url, probe(e, timeout)))
               for e in urls.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def status_text(p: dict) -> str:
    """One line: "connected - Qwen3.8-27B · 1 slot x 65536" or what went wrong."""
    if not p.get("up"):
        return p.get("error") or "not connected"
    parts = [p["served"]] if p.get("served") else []
    if p.get("n_ctx"):
        slots = p.get("slots") or 0
        window = f"{p['n_ctx']} tokens"
        parts.append(f"{slots} slot{'s' if slots != 1 else ''} x {window}" if slots else window)
    return "connected" + (" - " + " · ".join(parts) if parts else "")


def for_role(role: str) -> Endpoint:
    """The endpoint serving `role`. Raises EndpointError on a broken catalogue."""
    data, error = load_catalogue()
    if error:
        raise EndpointError(error)
    if data is None:
        return _from_env()
    if not (data.get("endpoints") or {}):
        return _from_env()
    roles = data.get("roles") or {}
    name = roles.get(role) or roles.get("agent") or next(iter(data["endpoints"]))
    return _named(data, name)


def entry_for_role(role: str) -> dict:
    """The raw catalogue entry serving `role` - what it is, what it is for and
    how it is sampled - or {} when there is no catalogue. Never raises: a page
    asking what a model is should not be the thing that breaks a run."""
    try:
        data, error = load_catalogue()
        if error or data is None:
            return {}
        if not (data.get("endpoints") or {}):
            return {}
        roles = data.get("roles") or {}
        name = roles.get(role) or roles.get("agent") or next(iter(data["endpoints"]))
        return dict((data.get("endpoints") or {}).get(name) or {})
    except Exception:
        return {}


def assignments() -> dict[str, Endpoint]:
    """Every role and the endpoint serving it. Raises EndpointError like for_role."""
    return {role: for_role(role) for role in ROLES}


def state(base_url: str) -> State:
    """What this process has learned about the endpoint at `base_url`."""
    key = (base_url or "").rstrip("/")
    with _LOCK:
        found = _STATES.get(key)
        if found is None:
            found = _STATES[key] = State()
        return found
