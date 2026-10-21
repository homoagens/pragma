# replace_in_file

Replace an exact substring in a file (`old` must appear verbatim; `count=-1` for every occurrence): the cheapest way to change part of a file you have seen. Deterministic; it takes no `overwrite`.

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
- Use this when you already know the exact text to change.
- For a renaming pass across all occurrences, pass `count=-1`.

## Examples

```json
{ "action": "replace_in_file", "args": { "path": "/home/me/proj/config.py", "old": "DEBUG = True", "new": "DEBUG = False" } }
{ "action": "replace_in_file", "args": { "path": "/home/me/proj/app.py", "old": "oldFunctionName", "new": "newFunctionName", "count": -1 } }
```

## Do not

- Use this with a substring that may match more than intended unless `count` is set appropriately
