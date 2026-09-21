#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""The sampling table: what is in force, and where to change it.

    python tools/pragma_sampling.py            what every model's table says
    python tools/pragma_sampling.py --write    write it to ~/.pragma/sampling.json

WHY IT EXISTS. The table is data - a model's own recommended numbers, one row
per kind of task - and a project picks a row by name. Data nobody can see is
a constant with extra steps: without this there was no way to read what the
numbers were, and ~/.pragma/sampling.json did not exist until someone wrote it
from a docstring.

--write puts the built-in table in that file, as a starting point to edit. It
never overwrites one that is already there: what is on disk is someone's
work, and the defaults are a keystroke away in the source.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
os.environ.setdefault("PRAGMA_NO_ENDPOINT_PROBE", "1")

import config  # noqa: E402

GREY, RESET = "\033[38;5;242m", "\033[0m"


def accent() -> str:
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        raw = "178;132;255"
    return "\033[38;2;" + raw + "m" if sys.stdout.isatty() else ""


def ask_the_endpoint() -> str:
    """What the agent's endpoint says it is serving, or "".

    Asked, not assumed. This tool switches the import-time probe off so it
    starts instantly, which left config.SERVED_MODEL empty and the table
    falling back to DEFAULT_MODEL - a LABEL, "llama3.2" until someone sets
    it. The page then named a model nobody was serving and blamed the
    endpoint for the table it had chosen itself. One question costs a second
    and is the only thing that can answer this honestly.
    """
    try:
        import llm_client
        ok, _ = llm_client.ping_models(timeout=4)
        return config.SERVED_MODEL.strip() if ok else ""
    except Exception:
        return ""


def show() -> None:
    a = accent()
    r = RESET if a else ""
    g = GREY if a else ""
    served = ask_the_endpoint()
    in_force, _ = config.profile_table()
    print()
    print(f"  {a}sampling table{r}")
    print(f"  {g}{config._PROFILES_FILE}"
          f"{' - not there yet, --write starts it' if not config._PROFILES_FILE.is_file() else ''}{r}")
    print()
    # Every knob llama.cpp acts on, in the order a person reads them - but a
    # column is only drawn when some row of that table sets it. A table of
    # dashes says nothing except that the terminal is wide.
    ORDER = ("temperature", "top_p", "top_k", "min_p",
             "presence_penalty", "frequency_penalty", "repeat_penalty")
    for model, table in config.SAMPLING_PROFILES.items():
        used = [k for k in ORDER if any(k in row for row in table.values())]
        used += sorted({k for row in table.values() for k in row} - set(ORDER))
        head = "".join(f"{k.replace('_penalty', '_pen.'):>16}" for k in used)
        mark = "   <- what this endpoint reads" if model == in_force else ""
        print(f"  {a}{model}{r}{g}{mark}{r}")
        print(f"    {g}{'row':<20}{head}{r}")
        for row, values in table.items():
            cells = "".join(f"{values[k]:>16g}" if k in values else f"{'-':>16}" for k in used)
            print(f"    {row:<20}{cells}")
        print()
    # Which of the two routes matched, because `(qwen36)` on its own does not
    # say whether it was the endpoint's name or the model's, and the two come
    # apart the day a port is renamed or reloaded with something else.
    here = config.agent_endpoint_name()
    by_name = bool(here) and in_force != "default" and config._plain(here) == config._plain(in_force)
    where = f"the agent talks to `{here}`" if here else "the agent's endpoint"
    if by_name:
        print(f"  {g}{where}, and a table has that name, so its rows are the ones sent{r}")
    elif in_force != "default" and served:
        print(f"  {g}{where}; no table has that name, so `{in_force}` was matched on the"
              f" model it serves ({served}){r}")
    elif served:
        print(f"  {g}{where} serves {served}, which no table names: the default rows"
              f" are sent{r}")
        print(f"  {g}give it a key - the endpoint's name, or the model's - and it will"
              f" be read{r}")
    else:
        print(f"  {g}{where} did not answer, and no table has its name: nothing can be"
              f" said about{r}")
        print(f"  {g}which rows it would send until it does.{r}")
    print(f"  {g}a project picks a row with /settings: general or coding{r}")
    print()


def write(force: bool = False) -> int:
    path = config._PROFILES_FILE
    if path.is_file() and not force:
        print(f"  {path} is already there - left alone.")
        print("  Delete it, or edit it: what is in it wins over the built-in table.")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.SAMPLING_PROFILES, indent=2) + "\n", encoding="utf-8")
    print(f"  written {path}")
    print("  Every row in it is read over the built-in one, field by field, so")
    print("  a row you cut back to one number keeps the rest.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="write the built-in table to ~/.pragma/sampling.json")
    ap.add_argument("--force", action="store_true",
                    help="with --write: replace a file that is already there")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if args.write:
        return write(args.force)
    show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
