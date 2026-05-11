# append_file

Append text to the end of an existing file. No LLM involved.

---

## Parameters

- `path` (str): File to append to (must exist).
- `content` (str): Text to append.
- `encoding` (str, optional, default "utf-8"): File encoding.
- `ensure_newline` (bool, optional, default True): Adds a leading newline if the file does not already end with one.

## Returns

`"OK: appended N bytes to <path>"` or `"ERROR: ..."`.

## Notes

- Pure file append. Cannot hit the LLM token limit.
- Use this for adding new functions/sections at the end of an existing file.
- For NEW files, use `write_file` instead.

## Examples

```json
{ "action": "append_file", "args": { "path": "C:\\proj\\sim.js", "content": "\nfunction newFeature() {\n  return 1;\n}\n" } }
```
