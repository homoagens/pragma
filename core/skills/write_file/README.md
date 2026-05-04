# write_file

Create or overwrite a file with the given content.

---

## Parameters

- `path` (str): Absolute or relative path to the file.
- `content` (str): Text content to write.
- `encoding` (str, optional, default "utf-8"): File encoding.
- `create_parents` (bool, optional, default True): Create intermediate directories if they do not exist.

## Returns

`"OK: written N bytes to <path>"` or `"ERROR: ..."` on failure.

## Notes

- Always overwrites the file if it already exists.
- Parent directories are created by default.

## Examples

```json
{ "action": "write_file", "args": { "path": "C:\\project\\hello.py", "content": "print('hello')\n" } }
{ "action": "write_file", "args": { "path": "C:\\project\\config.json", "content": "{\"debug\": false, \"port\": 8080}\n" } }
```

## Do not

- Use double quotes inside Python string literals in `content` — they break JSON encoding; use single quotes instead
- Use triple-quoted strings in `content` — they are unreliable inside JSON; use `\n` for newlines
- Write `\\` when you mean a single backslash in a Python string — in JSON `\\\\` → file contains `\\` → Python sees `\`
- Use `write_file` to modify an existing file — use `edit_file` for targeted changes to avoid overwriting unintended sections
- Write large files in one call if the content is complex — split into multiple `write_file` calls, one logical section at a time
