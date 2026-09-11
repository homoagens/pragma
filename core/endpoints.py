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
#         "big":   {"url": "http://127.0.0.1:8100/v1"},
#         "small": {"url": "http://127.0.0.1:8190/v1", "model": "",
#                   "key": "", "key_env": ""}
#       },
#       "roles": {"agent": "big", "recall": "small", "memory": "big"}
#     }
#
# It is global rather than per project because the machines are the same
# whichever project is open, and it lives outside every backup, so no address
# or key ends up in a zip. A key is written either as "key" or, to keep it out
# of the file, as "key_env": the name of an environment variable holding it.
#
# With no catalogue, every role uses the endpoint in .env (LLM_BASE_URL,
# LLM_API_KEY, DEFAULT_MODEL) exactly as before, and that endpoint is also
# reachable from the catalogue under the name "default". A role the catalogue
# does not assign follows the agent.
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

# SUMMARIZER is deliberately absent: it compresses the agent's own history, so
# it runs where the agent runs.
_ROLE_OF_FACULTY = {
    "CURATOR":        "recall",
    "SEGMENTER":      "memory",
    "CONSOLIDATOR":   "memory",
    "RECONSOLIDATOR": "memory",
    "ABSTRACTOR":     "memory",
    "REFLECT":        "memory",
}


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


_STATES: dict[str, State] = {}
_LOCK = threading.Lock()
_CATALOGUE: dict = {"stamp": None, "data": None, "error": ""}


def role_of(faculty: str) -> str:
    """The role a faculty's calls belong to; unlabelled calls are the agent's."""
    return _ROLE_OF_FACULTY.get((faculty or "").strip().upper(), "agent")


def catalogue_path() -> Path:
    raw = os.environ.get("PRAGMA_ENDPOINTS", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".pragma" / "endpoints.json"


def _problem(data) -> str:
    """What makes a parsed catalogue unusable, or ""."""
    if not isinstance(data, dict):
        return "the top level must be an object with \"endpoints\" and \"roles\""
    eps = data.get("endpoints", {})
    roles = data.get("roles", {})
    if not isinstance(eps, dict) or not isinstance(roles, dict):
        return "\"endpoints\" and \"roles\" must both be objects"
    for name, e in eps.items():
        if not isinstance(e, dict) or not str(e.get("url") or "").strip():
            return f"endpoint \"{name}\" has no \"url\""
    for role, name in roles.items():
        if role not in ROLES:
            return f"\"{role}\" is not a role; the roles are {', '.join(ROLES)}"
        if name != "default" and name not in eps:
            return f"role \"{role}\" names \"{name}\", which is not in \"endpoints\""
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


def _from_env() -> Endpoint:
    return Endpoint(
        name="default",
        base_url=(config.LLM_BASE_URL or DEFAULT_BASE_URL).rstrip("/"),
        api_key=config.LLM_API_KEY or "",
        model=config.DEFAULT_MODEL or "",
    )


def _named(data: dict, name: str) -> Endpoint:
    eps = data.get("endpoints") or {}
    if name == "default" and name not in eps:
        return _from_env()
    e = eps[name]
    key = str(e.get("key") or "")
    if not key and e.get("key_env"):
        key = os.environ.get(str(e["key_env"]), "")
    return Endpoint(name=name, base_url=str(e["url"]).strip().rstrip("/"),
                    api_key=key, model=str(e.get("model") or ""))


def for_role(role: str) -> Endpoint:
    """The endpoint serving `role`. Raises EndpointError on a broken catalogue."""
    data, error = load_catalogue()
    if error:
        raise EndpointError(error)
    if data is None:
        return _from_env()
    roles = data.get("roles") or {}
    return _named(data, roles.get(role) or roles.get("agent") or "default")


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
