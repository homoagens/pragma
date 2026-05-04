# todo_execute

Iterate a task list from a JSON file and dispatch each task to its assigned skill.

---

## Parameters

- `todo_path` (str, optional, default "todo.json"): Path to the JSON file produced by `todo_create`.
- `dry_run` (bool, optional, default False): If True, print the execution plan without running any skill.

## Returns

Execution log with per-task results and a final summary (`done / failed / skipped out of total`), or `"ERROR: ..."`.

## Notes

- Tasks without an `assignee` are skipped; tasks whose `assignee` is not in `ALL_SKILLS` are also skipped.
- Each task is called with its `description` as the sole argument; complex tasks may need a dedicated wrapper skill.
- In dry-run mode, no skills are executed; only the plan is printed.
- `ALL_SKILLS` is imported lazily inside the function to avoid circular import issues.
