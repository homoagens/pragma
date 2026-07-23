# git_status

Show the state of the git repository: current branch, position relative to
upstream, and which files are staged, modified or untracked, plus the last few
commits.

**Read-only.** This skill never stages, commits, pushes or discards anything.
Committing is a decision for the user; use `execute_command` only if the user
explicitly asked for it.

---

## Parameters

- `path` (str, optional, default "."): Any path inside the repository.
- `max_files` (int, optional, default 60): Cap on listed files.

## Returns

A summary block, or `"ERROR: ..."` if the path is not inside a git repository
or git is unavailable.

## Notes

- Answers "where am I and what have I touched?" in one call.
- Use `git_diff` to see the content of the changes.
