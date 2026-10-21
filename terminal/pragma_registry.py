#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""The registry of projects, ~/.pragma/registry.json, read and written here.

The launcher, the home screen and the conversation each had their own copy of
reading it, and two of writing it, which did not quite agree: one matched a
name whatever its case and one exactly, one removed a setting given an empty
value and one stored it. Nothing broke only because a new project may not take
a name that differs from another by case alone. One copy now, standard library
only, so the conversation loads it as readily as the launcher.

The Windows launcher reads and writes the same file, in Pragma.psm1.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REGISTRY = Path.home() / ".pragma" / "registry.json"


def read() -> list[dict]:
    """The registered projects, or nothing when the file cannot be read."""
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [e for e in data if isinstance(e, dict) and e.get("name")]


def write(entries: list[dict]) -> None:
    """All of them, replaced at once: a reader never sees half a file."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def _same(a, b) -> bool:
    return str(a or "").lower() == str(b or "").lower()


def by_name(name: str) -> dict | None:
    """The project of that name, whatever its case."""
    return next((e for e in read() if _same(e["name"], name)), None)


def settings_of(name: str) -> dict:
    """What a project has decided for itself."""
    return dict((by_name(name) or {}).get("settings") or {})


def save_setting(name: str, key: str, value) -> bool:
    """One setting of one project; whether there was such a project. An empty
    value REMOVES it: absent means the repository default, which is what
    someone clearing a field asked for. A value is a string, or a list for the
    one setting that is one."""
    entries = read()
    found = False
    for e in entries:
        if not _same(e["name"], name):
            continue
        found = True
        settings = dict(e.get("settings") or {})
        if value in ("", []):
            settings.pop(key, None)
        else:
            settings[key] = value
        e["settings"] = settings
    if found:
        write(entries)
    return found
