# write_file

Create or overwrite a file with the given content.

---

## Parameters

- `path` (str): Absolute or relative path to the file.
- `content` (str): Text content to write.
- `encoding` (str, optional, default "utf-8"): File encoding.
- `create_parents` (bool, optional, default True): Create intermediate directories if they do not exist.

## Returns

`"OK: written N bytes to <path>"` or `"ERROR: ..."` on failure.

## Notes

- Always overwrites the file if it already exists.
- Parent directories are created by default.
