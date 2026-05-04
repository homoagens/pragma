# memory_store

Evaluate content for long-term value and, if worthwhile, save it to a persistent JSON memory file.

---

## Parameters

- `content` (str): Raw text to evaluate and potentially save.
- `memory_path` (str, optional, default "memory.json"): Path of the JSON memory file.
- `tag` (str, optional, default ""): Optional category label (e.g. `"fact"`, `"preference"`, `"error"`).

## Returns

`"SAVED: <key> — <summary>"` or `"SKIP: <reason>"` or `"ERROR: ..."`.

## Notes

- The LLM decides whether the content is worth saving; trivial or purely procedural content is skipped.
- Each saved entry has: `key` (snake_case, max 5 words), `summary` (one sentence), `tag`, `ts` (ISO 8601 UTC).
- Entries are appended; the file is created if it does not exist.
