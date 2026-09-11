#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""Interactive configuration for Pragma — writes the OpenAI-compatible
endpoint settings into .env.

Reached as /configure, from the launcher's home prompt or inside a
conversation. It also runs on its own, for a machine being set up by hand:

    venv\Scripts\python.exe tools\pragma_configure.py

Ctrl+D goes back from any question, at any point of the line, and nothing is
written: the three answers are only saved once all three are given. The exit
code says which happened, 0 saved and 3 went back, so the caller knows whether
there is a result worth pausing on.

All the logic is here rather than in the shell wrapper it used to have, so
reading the current values, prompting, backing up, upserting and the health
check are robust to any characters already present in .env.
"""

from pathlib import Path
import shutil
import sys

# The repository root, one level up from tools/. Not the current directory:
# /configure runs with the project workspace as cwd, and writing a .env
# there would create a second one that nothing reads.
ENV          = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_URL  = "http://127.0.0.1:8080/v1"
KEYS         = ("LLM_BASE_URL", "DEFAULT_MODEL", "LLM_API_KEY")
WENT_BACK    = 3
GREY, RESET  = "\033[38;5;242m", "\033[0m"


def read_current() -> dict:
    """Current values of the managed keys (for prompt defaults)."""
    cur = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() in KEYS:
                cur[k.strip()] = v
    return cur


def make_session():
    """A prompt where Ctrl+D always goes back, or None for plain input()."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        from prompt_toolkit import PromptSession
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

    return PromptSession(key_bindings=kb)


def ask(session, prompt: str, default: str, secret: bool = False) -> str:
    """One answer; Enter keeps the current value. Raises EOFError to go back.

    The current value and the way out are shown in grey on the empty line,
    where the answer is about to go, rather than in brackets before it: the
    hint is visible while there is nothing typed, and gone once there is.
    """
    if session is None:
        shown = ("set" if default else "") if secret else default
        suffix = f" [{shown}]" if shown else ""
        reply = input(f"  {prompt}{suffix}: ").strip()
        return reply or default
    from prompt_toolkit.formatted_text import ANSI
    if secret:
        current = "a key is set" if default else "empty"
    else:
        current = default or "empty"
    placeholder = ANSI(f"{GREY}{current} · enter keeps it · ctrl+D to go back{RESET}")
    reply = session.prompt(ANSI(f"  {prompt}: "), placeholder=placeholder,
                           is_password=secret).strip()
    return reply or default


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    print("  Pragma talks to ONE OpenAI-compatible endpoint: POST {URL}/chat/completions")
    print("  The base URL must end in /v1. Examples:")
    print("    llama.cpp http://127.0.0.1:8080/v1   LM Studio http://127.0.0.1:1234/v1")
    print("    Ollama    http://127.0.0.1:11434/v1  vLLM      http://127.0.0.1:8000/v1")
    print()

    cur = read_current()
    session = make_session()
    try:
        base = ask(session, "Backend URL (ends in /v1)", cur.get("LLM_BASE_URL") or DEFAULT_URL)
        # Empty is the good answer for a single-model server: the request field
        # is then filled from whatever the endpoint reports, so it cannot go
        # stale the day another model is loaded on the same port. Name one only
        # when the endpoint hosts several and the field selects between them.
        model = ask(session, "Model name (empty = ask the endpoint)", cur.get("DEFAULT_MODEL", ""))
        key = ask(session, "API key (empty for local servers)", cur.get("LLM_API_KEY", ""), secret=True)
    except (EOFError, KeyboardInterrupt):
        print()
        print("  back - nothing changed.")
        return WENT_BACK
    new_vals = {"LLM_BASE_URL": base, "DEFAULT_MODEL": model, "LLM_API_KEY": key}

    # Back up, then upsert the three keys preserving every other line verbatim.
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    if ENV.exists():
        shutil.copyfile(ENV, ENV.parent / (ENV.name + ".bak"))
        print("  Backed up existing .env -> .env.bak")
    kept = [ln for ln in lines
            if not any(ln.lstrip().startswith(k + "=") for k in KEYS)]
    out  = kept + [f"{k}={new_vals[k]}" for k in KEYS]
    ENV.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    print(f"  Wrote {ENV}")

    # Health check: GET {base}/models on the OpenAI-compatible endpoint.
    print(f"\n  Checking {base}/models ...")
    try:
        import requests
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = requests.get(f"{base.rstrip('/')}/models", headers=headers, timeout=5)
        if r.status_code == 200:
            print("  OK - endpoint reachable.")
        else:
            print(f"  WARNING - endpoint returned HTTP {r.status_code}. Is the server running?")
            print("  Pragma runs either way; come back to /configure when the server is up.")
    except Exception as e:
        # Said in one line. A urllib3 connection failure is five lines of
        # nested exception text, and this prints inside the harness, where it
        # pushed the answer off the screen and then got truncated mid-word.
        why = " ".join(str(e).split())
        if "Max retries exceeded" in why:
            why = "nothing is listening at that address"
        print(f"  WARNING - could not reach the endpoint ({why[:110]}).")
        print("  Pragma runs either way; come back to /configure when the server is up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
