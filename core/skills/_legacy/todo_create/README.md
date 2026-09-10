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

## Examples

```json
{ "action": "todo_create", "args": { "tasks": [{"description": "Read the config file", "priority": "high", "assignee": "read_file"}, {"description": "Parse the JSON structure", "priority": "medium", "assignee": "parse_document"}] } }
{ "action": "todo_create", "args": { "tasks": "Install dependencies\nRun tests\nDeploy", "output_path": "C:\\project\\todo.json" } }
```

## Do not

- Call `todo_execute` after `todo_create` — Pragma does not use `todo_execute`; execute tasks manually step by step
- Create a todo list for simple tasks (1-3 steps) — only use it for genuinely complex multi-step work
- Set `assignee` to a skill that does not exist in the registry — it will be skipped with a warning
- Recreate the todo list mid-task — create it once at the beginning, then follow it
