# write_file

Create a NEW file with the given content. Refuses to overwrite existing files unless explicitly authorized.

---

## Parameters

- `path` (str): Absolute or relative path to the file.
- `content` (str): Text content to write.
- `encoding` (str, optional, default `"utf-8"`): File encoding.
- `create_parents` (bool, optional, default `True`): Create intermediate directories if they do not exist.
- `overwrite` (bool, optional, default `False`): Allow replacing an existing file. By default the skill returns an error if the target already exists.

## Returns

- `"OK: written N bytes to <path>"` on success. When N exceeds `WRITE_FILE_SOFT_LIMIT` a soft warning is appended advising future edits to use the surgical skills.
- `"ERROR: file already exists at <path> ..."` when the target exists and `overwrite` is `False`. The error lists the recommended surgical skills.
- `"ERROR: content too large ..."` when the supplied content exceeds `WRITE_FILE_HARD_LIMIT` (default 6000 bytes). The error explains the incremental-build pattern (scaffolding + append_file per section).
- `"ERROR writing ..."` on I/O failure.

## Notes

- Default behavior is intentionally restrictive: rewriting an existing file ships the whole new content inside the JSON action and is the #1 cause of `finish_reason=length` truncation. Surgical skills are cheaper and safer.
- For large NEW files the same problem applies — a single write of ~8 KB can truncate the LLM's JSON response mid-string. The hard limit forces incremental construction.
- Parent directories are created by default.

## Examples

```json
{ "action": "write_file", "args": { "path": "C:\\project\\hello.py", "content": "print('hello')\n" } }
{ "action": "write_file", "args": { "path": "C:\\project\\config.json", "content": "{\"debug\": false, \"port\": 8080}\n" } }
{ "action": "write_file", "args": { "path": "C:\\project\\plan.json", "content": "{...}", "overwrite": true } }
```

## When to use it

- The file does NOT exist yet (a new module, a new config, a new HTML page).
- A small wholly-generated file (< 100 lines) needs to be rewritten end to end — pass `overwrite=true`.

## When NOT to use it

- The file already exists and you only need to add or change part of it. Use:
    - `replace_in_file(path, old, new)` — deterministic substring replace, no LLM call
    - `insert_after(path, anchor, content)` / `insert_before(path, anchor, content)` — deterministic block insert
    - `append_file(path, content)` — deterministic append
    - `edit_file(path, instruction)` — interpret-and-patch via LLM (last resort, costs one LLM call)
- The file is large (> ~200 lines). Rewriting it whole is almost certainly going to truncate the JSON; prefer surgical skills.

## Do not

- Use double quotes inside Python string literals in `content` — they break JSON encoding; use single quotes instead.
- Use triple-quoted strings in `content` — they are unreliable inside JSON; use `\n` for newlines.
- Write `\\` when you mean a single backslash in a Python string — in JSON `\\\\` → file contains `\\` → Python sees `\`.
- Set `overwrite=true` reflexively. Read the existing file first and decide whether a targeted edit fits.
