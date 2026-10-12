# read_file

Read the contents of a local file, optionally selecting a line range.

---

## Parameters

- `path` (str): Absolute or relative path to the file.
- `encoding` (str, optional, default "utf-8"): File encoding.
- `start_line` (int, optional, default 0): First line to return (1-based). Must be > 0 together with `end_line`.
- `end_line` (int, optional, default 0): Last line to return (1-based, inclusive).

## Returns

File content as a string, or `"ERROR: ..."` on failure.

## Notes

- If only `start_line` and `end_line` are both > 0, returns only those lines.
- If the file does not exist or is a directory, returns an error string (never raises).
