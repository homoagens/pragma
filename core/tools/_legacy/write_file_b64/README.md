# write_file_b64

Same semantics as `write_file`, but the content arrives **base64-encoded**. Sidesteps the JSON-escape ambiguity that makes `write_file` fail on long content (literal `\n`, mixed quotes, backslashes, control characters).

---

## Parameters

- `path` (str): Target file path.
- `content_b64` (str): Base64 of the bytes to write.
- `encoding` (str, optional, default `"utf-8"`): File encoding for writing.
- `create_parents` (bool, optional, default `True`): Create intermediate directories.
- `overwrite` (bool, optional, default `False`): Allow replacing an existing file. Same semantic as `write_file.overwrite`.

## Returns

- `"OK: written N bytes to <path>"` on success.
- `"ERROR: file already exists at <path> ..."` when target exists and `overwrite=False`.
- `"ERROR: content too large ..."` when the decoded size exceeds `WRITE_FILE_HARD_LIMIT` (base64 fixes escape ambiguity, NOT the size budget).
- `"ERROR: invalid base64 ..."` / `"ERROR: decoded bytes are not valid <encoding> ..."` on decode failure.
- `"ERROR writing ..."` on I/O failure.

## When to use it (vs `write_file`)

Pick `write_file_b64` over `write_file` whenever any of these is true:

- **The content is large** (> ~5 KB) — JSON compliance from the model degrades on long string fields.
- **The content has escape-sensitive characters**: newlines, mixed quotes (`'` and `"` together), backslashes, control chars, source code with `\n` inside strings.
- **A previous `write_file` attempt failed** with "missing required argument" or json-repair note about lost keys — the JSON layer mangled the call.

For short, simple content (< 1-2 KB, plain text) keep using `write_file` — it's slightly less work.

## Examples

```python
# Python side: encode first
import base64
src = '<html>\n<body>\n  <h1>Hi</h1>\n</body>\n</html>'
b64 = base64.b64encode(src.encode()).decode()
```

```json
{
  "action": "write_file_b64",
  "args": {
    "path":        "C:\\proj\\index.html",
    "content_b64": "PGh0bWw+Cjxib2R5PgogIDxoMT5IaTwvaDE+CjwvYm9keT4KPC9odG1sPg==",
    "overwrite":   true
  }
}
```

## Notes

- Pure base64-decode + `Path.write_text`. No LLM call.
- The same `WRITE_FILE_HARD_LIMIT` / `WRITE_FILE_SOFT_LIMIT` thresholds apply: base64 fixes the wire-encoding problem, not the output token budget. For files > `WRITE_FILE_HARD_LIMIT`, still split into scaffolding + `append_file` per section.
- For modifying EXISTING files, use `replace_in_file_b64` (or `replace_in_file`, `insert_after`, etc.) — not this skill.

## Do not

- Use this skill for content < 1 KB of plain text — `write_file` is simpler.
- Forget to set `overwrite=true` when intentionally replacing a file.
- Try to bypass the size limit — it applies to decoded content, not to the base64 string length.
