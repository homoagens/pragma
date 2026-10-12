# list_dir

List the contents of a directory with type, size, and modification time.

---

## Parameters

- `path` (str, optional, default "."): Directory to list.
- `show_hidden` (bool, optional, default False): Include entries whose names start with `.`.
- `max_entries` (int, optional, default 200): Maximum number of entries to display.

## Returns

A tabular string with columns `type`, `size`, `modified`, `name`, or `"ERROR: ..."`.

## Notes

- Entries are sorted alphabetically.
- If there are more entries than `max_entries`, a truncation notice is appended.
