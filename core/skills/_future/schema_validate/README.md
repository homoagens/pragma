# schema_validate

Verify that a JSON string is well-formed and matches required fields and types.

---

## Parameters

- `data` (str): JSON string to validate.
- `required_fields` (str, optional, default ""): Comma-separated list of mandatory field names, e.g. `"id,name,status"`.
- `field_types` (str, optional, default ""): JSON object mapping field names to expected types (`"str"`, `"int"`, `"float"`, `"bool"`, `"list"`, `"dict"`), e.g. `'{"id":"int","name":"str"}'`.

## Returns

`"VALID"` or `"INVALID:\n  - <reason>\n  - ..."`.

## Notes

- Checks JSON syntax first; if invalid, returns immediately without field checks.
- Type checking uses exact isinstance matches (no coercion).
- Fields listed in `field_types` that are absent from `data` are not flagged as type errors (only missing required fields are).
