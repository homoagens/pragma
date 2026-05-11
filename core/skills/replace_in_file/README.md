# replace_in_file

Deterministic find-and-replace in a file. No LLM involved — equivalent to Python's `str.replace`.

---

## Parameters

- `path` (str): File to modify.
- `old` (str): Exact substring to find (must exist verbatim).
- `new` (str): Replacement substring.
- `count` (int, optional, default 1): Number of occurrences to replace. Use `-1` to replace all.
- `encoding` (str, optional, default "utf-8"): File encoding.

## Returns

`"OK: replaced N occurrence(s) in <path>"` or `"ERROR: ..."`.

## Notes

- Pure str.replace. Cannot hit the LLM token limit.
- Prefer this over `edit_file` when you already know the exact text to change.
- For a renaming pass across all occurrences, pass `count=-1`.

## Examples

```json
{ "action": "replace_in_file", "args": { "path": "C:\\proj\\config.py", "old": "DEBUG = True", "new": "DEBUG = False" } }
{ "action": "replace_in_file", "args": { "path": "C:\\proj\\app.py", "old": "oldFunctionName", "new": "newFunctionName", "count": -1 } }
```

## Do not

- Use this with a substring that may match more than intended unless `count` is set appropriately
