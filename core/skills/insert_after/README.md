# insert_after

Deterministic insert: place a block of content immediately after the first occurrence of an exact anchor string in a file. No LLM involved.

---

## Parameters

- `path` (str): File to modify.
- `anchor` (str): Exact substring to anchor the insertion (must exist verbatim in the file).
- `content` (str): Text to insert right after the anchor.
- `encoding` (str, optional, default "utf-8"): File encoding.

## Returns

`"OK: inserted N bytes after anchor in <path>"` or `"ERROR: ..."`.

## Notes

- Pure str search + slice + write. Cannot hit the LLM token limit.
- If the anchor ends mid-line, a newline is added before `content` to keep the file readable.
- Use this for adding functions/classes/blocks after a known marker (e.g. after `// END OF PLANETS`, after `def __init__:`).

## Examples

```json
{ "action": "insert_after", "args": { "path": "C:\\proj\\sim.js", "anchor": "];", "content": "\nlet comets = [];\n" } }
{ "action": "insert_after", "args": { "path": "C:\\proj\\app.py", "anchor": "def __init__(self):", "content": "\n        self.cache = {}\n" } }
```

## Do not

- Use a vague anchor that appears multiple times — only the FIRST occurrence is matched
- Pass a multi-line anchor with normalized whitespace — must match verbatim
