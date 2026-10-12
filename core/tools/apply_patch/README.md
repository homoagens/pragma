# apply_patch

Apply a unified diff — several hunks, across several files, in one call.

Unlike a substring replace, a diff carries its context lines. It is therefore
applied at the intended place or **refused**: it cannot silently patch the
wrong occurrence of a repeated string.

---

## Parameters

- `diff` (str): The unified diff text (`---` / `+++` / `@@` hunks).
- `diff_b64` (str): The same diff, base64-encoded. **Prefer this.** A diff is
  multi-line and full of quotes and backslashes — exactly the payload that
  breaks the JSON argument layer. base64 is pure ASCII and cannot be mangled.
  Pass either `diff` or `diff_b64`, never both.
- `cwd` (str, optional): Directory the paths in the diff are relative to.
- `dry_run` (bool, optional, default False): Verify it applies cleanly, change
  nothing.

## Returns

`"OK: applied N hunk(s) across M file(s): ..."`, a dry-run confirmation, or
`"ERROR: ..."`.

## Notes

- Paths may carry the usual `a/` and `b/` prefixes.
- **All-or-nothing**: the patch is verified first, so a failure changes nothing.
- If it does not apply, the file is not what the diff was built against — re-read
  it and rebuild the diff from its current content. Do not retry unchanged.
- Requires `git` on PATH, used purely as the patch engine: no repository is
  needed, and nothing is staged or committed.
- Pragma's own source files are refused.
