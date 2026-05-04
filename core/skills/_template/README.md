# my_skill

One-line description of what the skill does (used in SKILLS_SUMMARY — keep it under 15 words).

---

## Parameters

- `text` (str): input text to transform
- `mode` (str, optional, default `"upper"`): transformation mode — `"upper"` | `"lower"` | `"title"`
- `prefix` (str, optional, default `""`): string prepended to the result

## Returns

The transformed text as a string, or `"ERROR: <reason>"` if the input is invalid.

## Notes

- Always returns `str` — never raises exceptions
- Empty or whitespace-only `text` returns an error
- Invalid `mode` returns an error listing valid options

## Examples

```json
{ "action": "my_skill", "args": { "text": "hello world" } }
{ "action": "my_skill", "args": { "text": "hello world", "mode": "title", "prefix": "Result: " } }
```

## Do not

- Pass an empty string as `text` — it returns `ERROR: input must not be empty`
- Use an undocumented `mode` value — only `"upper"`, `"lower"`, `"title"` are valid
- Expect the result to include a trailing newline — it does not

---

## How to create a new skill

1. Copy this folder to `core/skills/<your_skill_name>/`
2. Rename the function in `skill.py` to match the folder name exactly
3. Update `README.md` with real documentation
4. Restart Pragma — the loader picks it up automatically

The skill appears in `SKILLS_SUMMARY` (system prompt) and is accessible via `get_skill_details`.
