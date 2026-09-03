# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# pragma_endpoint.py - what this window is talking to, and on what terms.
#
#     python tools/pragma_endpoint.py
#
# Prints one JSON object on stdout: the resolved endpoint, the model actually
# loaded there, the sampling the server would apply on its own, and the
# sampling this window sends. Nothing else, so the caller never parses prose.
#
# WHY BOTH SIDES. A sampling value is not meaningful alone: what applies is
# whichever of the two is present, and the settings page is where that choice
# is made. Showing only what the project sends leaves the operator guessing at
# the half they are handing over.
#
# The server's own values come from llama.cpp's /props, which is not part of
# the OpenAI API. A server that does not expose it simply yields no "server"
# block, which is reported rather than guessed at.
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT), str(_ROOT / "core")]

import config                    # noqa: E402
import llm_client                # noqa: E402

_KEYS = ("temperature", "top_k", "top_p", "min_p",
         "repeat_penalty", "presence_penalty", "frequency_penalty")


def _props(base_url: str, api_key: str, timeout: float = 4.0) -> dict | None:
    """llama.cpp's /props, which sits beside /v1 rather than under it."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    req = urllib.request.Request(root + "/props")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def main() -> int:
    out: dict = {}
    try:
        base_url, api_key = llm_client._resolved_endpoint(None, None)
    except Exception:
        base_url, api_key = config.LLM_BASE_URL, ""
    out["endpoint"] = base_url

    ok, detail = llm_client.ping_models(timeout=4)
    out["up"] = bool(ok)
    out["serving"] = (getattr(config, "SERVED_MODEL", "")
                      or config.DEFAULT_MODEL) if ok else ""
    out["detail"] = "" if ok else str(detail)[:120]
    out["configured_model"] = config.DEFAULT_MODEL

    # What the server would apply if this window sent nothing.
    server = {}
    if ok:
        props = _props(base_url, api_key)
        params = ((props or {}).get("default_generation_settings")
                  or {}).get("params") or {}
        for k in _KEYS:
            if k in params:
                server[k] = params[k]
        if props and "build_info" in props:
            out["build"] = str(props["build_info"])[:40]
        # n_ctx sits beside params, not inside it.
        gen = (props or {}).get("default_generation_settings") or {}
        if gen.get("n_ctx"):
            out["n_ctx"] = gen["n_ctx"]
    out["server"] = server
    out["server_readable"] = bool(server)

    # What this window sends. Absent means the field is omitted, which is what
    # hands that parameter to the server.
    sending: dict = {}
    if config.DEFAULT_TEMPERATURE is not None:
        sending["temperature"] = config.DEFAULT_TEMPERATURE
    sending.update(config.sampling_extras())
    out["sending"] = sending

    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
