# todo_create

Write a structured task list as a JSON file for later execution by todo_execute.

---

## Parameters

- `tasks`: Task list as a Python list of dicts, a JSON string, or plain newline-separated text.
- `output_path` (str, optional, default "todo.json"): Path of the output JSON file.

## Returns

`"OK: N tasks written to <path>"` or `"ERROR: ..."`.

## Notes

- Each task is normalized to: `id`, `description`, `priority` (high/medium/low), `dependencies` (list of ids), `assignee` (skill name), `status` (pending).
- Plain-text input (one task per line) is accepted; each line becomes a task with default fields.
- The output file includes a `created_at` ISO 8601 timestamp.
