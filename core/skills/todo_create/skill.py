# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import json
from pathlib import Path

from skills._utils import _now


def todo_create(tasks, output_path: str = "todo.json") -> str:
    """
    Write a structured task list as JSON.
    tasks : list of dicts, JSON string, or plain text (one task per line).
    Schema for each task:
        id          : int
        description : str
        priority    : "high" | "medium" | "low"
        dependencies: list[int]   (ids of prerequisite tasks)
        assignee    : str         (skill name or sub-agent)
        status      : "pending"   (default)

    Returns "OK: N tasks written to <path>" or an error message.
    """
    # ── Step 1: normalise to a raw list ──────────────────────────────────────
    # The agent may pass tasks as a Python list (already parsed from JSON args),
    # as a JSON string, or as plain newline-separated text.
    if isinstance(tasks, list):
        raw = tasks
    elif isinstance(tasks, dict):
        raw = tasks.get("tasks", [tasks])
    elif isinstance(tasks, str):
        try:
            parsed = json.loads(tasks)
            if isinstance(parsed, list):
                raw = parsed
            elif isinstance(parsed, dict) and "tasks" in parsed:
                raw = parsed["tasks"]
            else:
                raw = [parsed]
        except json.JSONDecodeError:
            # Plain text: one task per line
            lines = [ln.strip() for ln in tasks.strip().splitlines() if ln.strip()]
            raw = lines  # will be handled as strings in step 2
    else:
        return f"ERROR: unexpected tasks type: {type(tasks).__name__}"

    # ── Step 2: normalise each item to a dict ────────────────────────────────
    normalized = []
    for i, t in enumerate(raw):
        if isinstance(t, str):
            # Plain string → use as description
            t = {"description": t}
        elif not isinstance(t, dict):
            t = {"description": str(t)}
        normalized.append({
            "id":           t.get("id", i + 1),
            "description":  t.get("description", str(t)),
            "priority":     t.get("priority", "medium"),
            "dependencies": t.get("dependencies", []),
            "assignee":     t.get("assignee", ""),
            "status":       t.get("status", "pending"),
        })

    if not normalized:
        return "ERROR: no tasks provided"

    payload = {"tasks": normalized, "created_at": _now()}
    try:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"OK: {len(normalized)} tasks written to {output_path}"
    except Exception as e:
        return f"ERROR writing todo: {e}"
