# recall_episodes

Retrieve the most relevant episodes from the episodic memory store — keyword overlap plus a same-workspace boost, no LLM call.

---

## Parameters

- `query` (str, optional): Free text describing the upcoming task. Empty string returns the most recent episodes.
- `workspace` (str, optional): Current working directory. Episodes born in the same workspace get a score bonus (`EPISODE_WORKSPACE_BOOST`, default 2), so local history wins ties but relevant episodes from other projects can still surface.
- `top_k` (int, optional): How many episodes to return. `0` = `config.EPISODES_RECALL_TOP_K` (default 3).
- `store_dir` (str, optional): Episode store override. Default `config.EPISODES_DIR` (`~/.pragma/episodes`).

## Returns

- One compact block per episode: `- (date, workspace-marker, outcome) goal — interpretation`, followed by a `surprises:` line when present.
- `"(no episodes)"` when the store is empty or missing.

## Notes

- Deterministic: keyword overlap on goal + keywords + narrative + surprises; falls back to recency when nothing matches. Ties break on effective salience (stored salience discounted by time since last recall — see `core/episodes.py`).
- Recall reinforces: retrieved episodes get `last_recalled` refreshed and `salience` bumped (+0.1, cap 1.0) — remembering strengthens the memory and resets its decay.
- Forgetting is reversible: when the active zone can't fill `top_k` with keyword matches, the dormant zone (`episodes/dormant/`) is searched too, and matching episodes are **revived** — moved back to active with their age reset, marked `[revived from dormant memory]` in the output.
- Episodes are written by `episode_consolidate` at end of session; this skill only reads (plus the reinforcement/revival bookkeeping).

## Examples

```json
{ "action": "recall_episodes", "args": { "query": "fix the login bug in the flask app", "workspace": "C:\\proj" } }
{ "action": "recall_episodes", "args": { "query": "", "top_k": 5 } }
```
