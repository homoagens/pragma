# revert

Undo file edits made during this session.

Every file is copied aside automatically the first time the session modifies
it, so this restores it to how it was **before the session** — not before the
last of several edits. Files the session created are deleted.

---

## Parameters

- `path` (str, optional): One file to restore. Empty restores everything changed.
- `list_only` (bool, optional, default False): Report what could be restored,
  change nothing.

## Returns

A list of restored files, a list of what could be restored, or a notice that
nothing was modified.

## Notes

- Snapshots are automatic — there is nothing to arrange beforehand.
- Use it when an edit went wrong and rebuilding by hand would be guesswork.
- It cannot undo work outside the workspace, nor the effects of commands run
  through `execute_command`.
- Snapshots live in `.pragma_checkpoints/` inside the workspace.
