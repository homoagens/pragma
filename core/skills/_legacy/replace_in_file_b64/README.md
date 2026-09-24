# replace_in_file_b64

Deterministic find-and-replace where `old` and `new` are passed **base64-encoded**. Sidesteps every JSON-escape ambiguity that breaks the normal `replace_in_file` on files containing literal escape sequences.

---

## Parameters

- `path` (str): File to modify.
- `old_b64` (str): Base64 of the exact bytes to find. Must decode to a substring that exists verbatim in the file.
- `new_b64` (str): Base64 of the replacement bytes. Can be empty (deletion).
- `count` (int, optional, default `1`): Number of occurrences to replace. Use `-1` to replace all.
- `encoding` (str, optional, default `"utf-8"`): File encoding for reading/writing.

## Returns

- `"OK: replaced N occurrence(s) in <path>"`
- `"ERROR: ..."` with a hint when the decoded substring isn't found, including an escaped preview of what was decoded so you can debug the encoding.

## When to use it

Use this instead of `replace_in_file` whenever either side of the substitution contains characters that would be ambiguous through the JSON-arg layer:

- **Literal escape sequences inside files** — the classic case: a file accidentally contains `\n` as two characters (backslash + n) instead of a real newline, and you want to fix it. With normal `replace_in_file` you'd have to type `\\\\n` in JSON to get `\\n` to reach the skill, AND remember to use `\\n` (single escape) in `new` to insert a real newline. Both base64 payloads here are unambiguous.
- **Mixed quote styles, tabs, control characters** — anything where JSON escape rules get confusing.
- **Binary-ish patches** — small surgical fixes to text with non-printable bytes.

Otherwise prefer `replace_in_file` — it's simpler and doesn't require base64 encoding.

## Examples

Fix literal `\n` (backslash + n) → real newline:

```python
# In Python, base64-encode the strings yourself before calling:
#   old: r'fetch("/x", {\n  method:'    →  base64
#   new:  'fetch("/x", {\n  method:'    →  base64 (real newline)
import base64
old_b64 = base64.b64encode(r'fetch("/x", {\n  method:'.encode()).decode()
new_b64 = base64.b64encode( 'fetch("/x", {\n  method:'.encode()).decode()
```

```json
{
  "action": "replace_in_file_b64",
  "args": {
    "path":    "C:\\proj\\index.html",
    "old_b64": "ZmV0Y2goIi94Iiwge1xubWV0aG9kOg==",
    "new_b64": "ZmV0Y2goIi94Iiwge\nbWV0aG9kOg==",
    "count":   -1
  }
}
```

## Notes

- Pure base64-decode + `str.replace`. No LLM call.
- The error message when `old` is not found includes a decoded preview, so if you mis-encoded you can see exactly what bytes the skill received.

## Do not

- Use this skill for normal text replacements where JSON escape isn't an issue — `replace_in_file` is simpler.
- Forget that `old_b64` decodes to BYTES then decodes again to TEXT using `encoding`. Non-UTF-8 bytes raise an error rather than corrupting the file.
