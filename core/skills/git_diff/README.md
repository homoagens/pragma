# git_diff

Show what actually changed in the working tree, as a unified diff.

**Read-only.** This skill never stages, commits or reverts anything.

---

## Parameters

- `path` (str, optional, default "."): Any path inside the repository.
- `staged` (bool, optional, default False): Show the staged diff instead.
- `file` (str, optional): Limit the diff to a single path.
- `context_lines` (int, optional, default 3): Lines of context around changes.
- `max_chars` (int, optional, default 30000): Truncation cap.

## Returns

The unified diff, a no-changes notice, or `"ERROR: ..."`.

## Notes

- Worth running before concluding a task: a diff shows what *changed*, whereas
  re-reading a file only shows what it now contains.
- Large diffs are truncated; pass `file=...` to inspect one path at a time.
