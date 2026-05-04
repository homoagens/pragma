# web_fetch

Perform an HTTP GET request and return the response body as text.

---

## Parameters

- `url` (str): URL to fetch.
- `timeout` (int, optional, default 30): Request timeout in seconds.
- `max_chars` (int, optional, default 50000): Truncate the response body if longer.

## Returns

Response body as a string, or `"HTTP ERROR <code>: ..."`, `"CONNECTION ERROR: ..."`, `"TIMEOUT after Ns: <url>"`, or `"ERROR: ..."`.

## Notes

- Uses a fixed `User-Agent: homo-agens/agent-baseline` header.
- HTTP errors (4xx/5xx) return an error string rather than raising.
- No HTML parsing or extraction: pipe the result through `parse_document` if structured extraction is needed.
