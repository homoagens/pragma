# parse_document

Extract structured content from HTML or plain text using deterministic cleanup followed by LLM extraction.

---

## Parameters

- `content` (str): Raw document content, e.g. from `web_fetch`.
- `doc_type` (str, optional, default "auto"): `"html"`, `"markdown"`, `"plain"`, or `"auto"` (auto-detects).
- `extract` (str, optional, default ""): Extraction target: `"main_text"`, `"links"`, `"summary"`, `"code_blocks"`, or `""` (all meaningful content).
- `max_input_chars` (int, optional, default 20000): Truncate input to the LLM if longer.

## Returns

Extracted text string or `"ERROR: ..."`.

## Notes

- HTML is deterministically cleaned (script/style removed, anchors converted to `text [url]`, entities decoded) before being sent to the LLM.
- Auto-detection checks for HTML tags and Markdown headings in the first 500 chars.
- Content longer than `max_input_chars` is truncated with a `[truncated]` notice.
