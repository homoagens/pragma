# insert_before

Deterministic insert: place a block of content immediately before the first occurrence of an exact anchor string in a file. No LLM involved.

---

## Parameters

- `path` (str): File to modify.
- `anchor` (str): Exact substring to anchor the insertion (must exist verbatim in the file).
- `content` (str): Text to insert right before the anchor.
- `encoding` (str, optional, default "utf-8"): File encoding.

## Returns

`"OK: inserted N bytes before anchor in <path>"` or `"ERROR: ..."`.

## Notes

- Pure str search + slice + write. Cannot hit the LLM token limit.
- If the anchor starts mid-line, a newline is added after `content` to keep the file readable.

## Examples

```json
{ "action": "insert_before", "args": { "path": "C:\\proj\\app.py", "anchor": "if __name__ ==", "content": "def helper():\n    return 42\n\n" } }
```

## Do not

- Use a vague anchor that appears multiple times — only the FIRST occurrence is matched
