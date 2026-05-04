# memory_retrieve

Retrieve the most semantically relevant entries from a persistent JSON memory file.

---

## Parameters

- `query` (str): What to search for in memory.
- `memory_path` (str, optional, default "memory.json"): Path of the JSON memory file.
- `top_k` (int, optional, default 5): Maximum number of entries to return.

## Returns

Formatted entries as `"[key] (tag | ts)\n  summary"` blocks separated by blank lines, `"NO RESULTS: <reason>"`, `"MEMORY EMPTY"`, or `"ERROR: ..."`.

## Notes

- The LLM ranks all entries by semantic relevance to the query; only entries clearly relevant are selected.
- Returns at most `top_k` entries even if the LLM selects more.
- If the memory file does not exist, returns `"MEMORY EMPTY"` (not an error).
