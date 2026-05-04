# web_search

Query a search engine and return ranked snippets with URLs.

---

## Parameters

- `query` (str): Search query string.
- `num_results` (int, optional, default 10): Number of results to return.
- `engine` (str, optional, default "duckduckgo"): Search engine: `"duckduckgo"` (no API key) or `"serper"` (requires `config.SERPER_API_KEY`).

## Returns

Numbered list of results with title, URL, and snippet, or `"NO RESULTS"`, or `"ERROR: ..."`.

## Notes

- DuckDuckGo requires the `ddgs` or `duckduckgo_search` library (`pip install ddgs`).
- Serper requires a valid API key in `config.SERPER_API_KEY`.
- Query formulation quality affects result relevance; consider using `llm_invoke` upstream to refine the query.
