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

- Dependency, build and VCS directories (`venv`, `node_modules`, `.git`,
  `__pycache__`, `dist`, `build`, …) are always skipped, so a search from a
  project root returns the project's own code rather than library internals.
- Uses `ripgrep` when available, which additionally honours `.gitignore` and is
  dramatically faster on large trees; falls back to a pure-Python walk
  otherwise, applying the same directory exclusions.
- Results are truncated with a notice when `max_results` is reached.
- Invalid regex patterns return an error immediately.
