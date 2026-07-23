# replace_in_files

Deterministic find-and-replace across many files at once — the multi-file
counterpart of `replace_in_file`. Renaming a symbol project-wide costs one call
instead of one per file.

---

## Parameters

- `old` (str): Exact substring to find. Must exist verbatim.
- `new` (str): Replacement substring.
- `path` (str, optional, default "."): Directory (or a single file) to search.
- `file_glob` (str, optional, default "*"): Which files to consider, e.g. `*.py`.
- `dry_run` (bool, optional, default False): Report what would change, write nothing.
- `max_files` (int, optional, default 50): Safety cap on files modified.
- `encoding` (str, optional, default "utf-8").

## Returns

A report listing each modified file and its occurrence count, or `"ERROR: ..."`.

## Notes

- Every occurrence in every matching file is replaced.
- All candidates are validated before anything is written, so a rename cannot
  leave the project half-converted.
- Dependency and build directories are skipped; Pragma's own source files are
  refused and reported.
- If the number of matching files exceeds `max_files`, nothing is written —
  narrow the search or run with `dry_run=True` first.
