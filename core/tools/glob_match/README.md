# glob_match

Find files matching a glob pattern, relative to a base directory.

---

## Parameters

- `pattern` (str): Glob pattern, e.g. `**/*.py` or `*.json`. Supports `**`.
- `base_path` (str, optional, default "."): Root directory for the search.
- `max_results` (int, optional, default 300): Cap on returned paths.
- `include_ignored` (bool, optional, default False): Also return matches inside
  dependency and build directories.

## Returns

Newline-separated list of relative POSIX paths, or a no-match notice, or `"ERROR: ..."`.

## Notes

- Dependency, build and VCS directories (`venv`, `node_modules`, `.git`,
  `__pycache__`, `dist`, `build`, …) are skipped by default; a trailing line
  reports how many matches were skipped. Use `include_ignored=True` when you
  genuinely need to look inside them.
- Paths in the result are relative to `base_path` and use forward slashes.
- Results are truncated with a notice when `max_results` is reached.
- Returns an error if `base_path` does not exist.
