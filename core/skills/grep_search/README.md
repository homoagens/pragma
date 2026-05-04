# grep_search

Search for a regex pattern inside file contents, returning matching lines with file path and line number.

---

## Parameters

- `pattern` (str): Regular expression to search for.
- `path` (str, optional, default "."): Directory or single file to search.
- `file_glob` (str, optional, default "*"): File filter when `path` is a directory, e.g. `*.py`.
- `ignore_case` (bool, optional, default False): Case-insensitive matching.
- `max_results` (int, optional, default 100): Maximum number of matching lines to return.

## Returns

Matches as `"path:lineno: line_content"` entries (one per line), a no-match notice, or `"ERROR: ..."`.

## Notes

- Results are truncated with a notice when `max_results` is reached.
- Invalid regex patterns return an error immediately.
