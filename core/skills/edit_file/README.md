# edit_file

Apply a surgical text patch to a file using LLM-generated old/new text pairs.

---

## Parameters

- `path` (str): Path to the file to modify.
- `instruction` (str): Natural language description of the change to apply.

## Returns

`"OK: patch applied to <path>"` with old/new excerpts, `"SKIP: <reason>"` if no change was needed, or `"ERROR: ..."`.

## Notes

- The LLM produces an exact `old_text` substring (verbatim from the file) and a `new_text` replacement.
- If `old_text` is not found verbatim in the file, the skill returns an error with a hint about whitespace.
- Only the first occurrence of `old_text` is replaced.
- Depends on `read_file` and `write_file` internally (late imports).

## Examples

```json
{ "action": "edit_file", "args": { "path": "C:\\project\\app.py", "instruction": "Add error handling around the open() call on line 12" } }
{ "action": "edit_file", "args": { "path": "C:\\project\\config.py", "instruction": "Change DEBUG from True to False" } }
{ "action": "edit_file", "args": { "path": "C:\\project\\README.md", "instruction": "Replace the Installation section with instructions for Windows" } }
```

## Do not

- Call `edit_file` without first reading the file with `read_file` — the LLM needs the actual content to produce a correct `old_text`
- Use vague instructions like "fix the bug" — be specific: "change the return value from None to an empty list on line 34"
- Use `edit_file` for large rewrites (>30% of the file) — use `write_file` instead
- Expect it to apply multiple independent changes in one call — make one `edit_file` call per logical change
- Trust it blindly — always `read_file` after to verify the patch was applied correctly
