# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import json


def todo_execute(todo_path: str = "todo.json",
                 dry_run: bool = False) -> str:
    """
    [G] Iterate the task list and dispatch each task to the correct skill or agent.
    Handles status tracking and failures for each task.

    todo_path : JSON file produced by todo_create
    dry_run   : if True, show the plan without executing
    """
    from skills.read_file.skill import read_file
    from skills import ALL_SKILLS

    raw = read_file(todo_path)
    if raw.startswith("ERROR"):
        return raw

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"ERROR: invalid JSON in {todo_path}: {e}"

    # Supports both a plain list and the format produced by todo_create
    # {"tasks": [...], "created_at": "..."}
    if isinstance(parsed, list):
        tasks = parsed
    elif isinstance(parsed, dict) and "tasks" in parsed:
        tasks = parsed["tasks"]
    else:
        return "ERROR: the todo file does not contain a recognizable task list"

    lines: list[str] = []
    done = failed = skipped = 0

    for i, task in enumerate(tasks):
        desc     = task.get("description", f"task_{i}")
        assignee = task.get("assignee", "")
        priority = task.get("priority", "medium")

        if dry_run:
            lines.append(
                f"[DRY] {i+1}. {desc}\n"
                f"      assignee={assignee or '(none)'}  priority={priority}"
            )
            continue

        lines.append(f"\n[{i+1}] {desc}  (assignee={assignee or '(none)'}, priority={priority})")

        if not assignee:
            lines.append("  SKIP: no assignee defined")
            skipped += 1
            task["status"] = "skipped"
            continue

        if assignee not in ALL_SKILLS:
            lines.append(f"  SKIP: skill '{assignee}' not found")
            skipped += 1
            task["status"] = "skipped"
            continue

        fn = ALL_SKILLS[assignee]
        try:
            result = str(fn(desc))
            if result.startswith("ERROR"):
                lines.append(f"  FAIL: {result[:200]}")
                task["status"] = "failed"
                failed += 1
            else:
                lines.append(f"  OK: {result[:200]}")
                task["status"] = "done"
                done += 1
        except NotImplementedError:
            lines.append(f"  SKIP: skill '{assignee}' not yet implemented")
            skipped += 1
            task["status"] = "skipped"
        except Exception as e:
            lines.append(f"  FAIL: {e}")
            task["status"] = "failed"
            failed += 1

    if dry_run:
        return f"DRY RUN — {len(tasks)} tasks:\n" + "\n".join(lines)

    summary = (
        f"\nExecution complete: {done} done, {failed} failed, "
        f"{skipped} skipped out of {len(tasks)} total tasks"
    )
    return "\n".join(lines) + summary
