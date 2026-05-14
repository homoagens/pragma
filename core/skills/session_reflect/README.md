# session_reflect

[H] Reflective pass over a completed task — extracts durable, generalizable learnings and appends them to a cross-thread learnings store.

---

## Parameters

- `transcript` (str): The task narrative (thoughts + actions + observations).
- `store_path` (str, optional): Where to persist. Defaults to `config.LEARNINGS_PATH` (`~/.pragma/learnings.json`).
- `label` (str, optional): Short tag attached to every entry produced this round (e.g. `"web-coding"`).

## Returns

`"OK: saved learnings to <path> (lessons=A patterns=B user_prefs=C mistakes=D)"`, or `"SKIP: nothing worth learning"`, or `"ERROR: ..."`.

## Notes

- Uses one LLM call. The system prompt asks for empty arrays when nothing is worth recording — the skill returns SKIP in that case.
- Entries are bucketed by kind: `lessons`, `patterns`, `user_prefs`, `mistakes`.
- Cheap dedup: identical `text` values are skipped.
- Usually invoked automatically at the end of a task (`AUTO_REFLECT=true` in config). Can be called manually to reflect on a specific transcript.

## Example

```json
{ "action": "session_reflect", "args": { "transcript": "...full task log...", "label": "fem-cad" } }
```
