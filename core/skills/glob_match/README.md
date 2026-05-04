# glob_match

Find files matching a glob pattern, relative to a base directory.

---

## Parameters

- `pattern` (str): Glob pattern, e.g. `**/*.py` or `*.json`. Supports `**`.
- `base_path` (str, optional, default "."): Root directory for the search.

## Returns

Newline-separated list of relative POSIX paths, or a no-match notice, or `"ERROR: ..."`.

## Notes

- Paths in the result are relative to `base_path` and use forward slashes.
- Returns an error if `base_path` does not exist.
