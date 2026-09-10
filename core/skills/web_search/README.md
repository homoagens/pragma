# web_search

Query DuckDuckGo and return ranked snippets with URLs.

---

## Parameters

- `query` (str): Search query string.
- `num_results` (int, optional, default 10): Number of results to return.

## Returns

Numbered list of results with title, URL, and snippet, or `"NO RESULTS"`, or `"ERROR: ..."`.

## Notes

- Uses the `ddgs` library, already in requirements.txt. No API key.
- Query formulation quality affects result relevance; phrase the query carefully.
