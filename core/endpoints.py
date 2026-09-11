# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# endpoints.py — which endpoint a call goes to, and what is known about each.
#
# Pragma is growing from one endpoint to several: the agent on one model, the
# curator and the memory faculties on others, possibly on other machines. Two
# things live here.
#
# ROUTING. A call's role comes from the faculty making it - the name every
# faculty already sets with llm_client.faculty(). CURATOR is `recall`; the
# faculties that write memory are `memory`; anything unlabelled is `agent`:
# the agent's own steps, the summariser, the forced verdict. No call site
# names an endpoint, so a faculty added later is routed by the same rule
# without remembering to ask.
#
# STATE. What used to be one value per process is now one value per endpoint:
# the model it actually serves, and whether it turned out to reject tools or
# JSON schemas. A server without tools must not switch the agent's channel off
# for a different server, and an episode must not be filed under a model that
# did not write it. Keyed by base URL, so two roles on the same server share
# what was learned about it, and pointing a role elsewhere starts clean.
#
# For now every role resolves to the one endpoint in .env (LLM_BASE_URL,
# LLM_API_KEY, DEFAULT_MODEL), read on every call as it always was: the browser
# interface changes those values while the process runs. The catalogue in
# ~/.pragma/endpoints.json is the next step, and this is where it will be read.

from __future__ import annotations

import threading
from dataclasses import dataclass

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


def role_of(faculty: str) -> str:
    """The role a faculty's calls belong to; unlabelled calls are the agent's."""
    return _ROLE_OF_FACULTY.get((faculty or "").strip().upper(), "agent")


def for_role(role: str) -> Endpoint:
    """The endpoint serving `role`. Today the same one for all three."""
    return Endpoint(
        name="default",
        base_url=(config.LLM_BASE_URL or DEFAULT_BASE_URL).rstrip("/"),
        api_key=config.LLM_API_KEY or "",
        model=config.DEFAULT_MODEL or "",
    )


def state(base_url: str) -> State:
    """What this process has learned about the endpoint at `base_url`."""
    key = (base_url or "").rstrip("/")
    with _LOCK:
        found = _STATES.get(key)
        if found is None:
            found = _STATES[key] = State()
        return found
