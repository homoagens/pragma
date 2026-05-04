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
