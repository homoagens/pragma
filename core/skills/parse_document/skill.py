from __future__ import annotations

import re

import llm_client
from json_parser import extract_json


_PARSE_SYSTEM = """You are a document content extractor.
Given cleaned document text and an extraction target, extract the requested content.

Respond with ONLY a JSON object:
{
  "result": "the extracted content as a clean string",
  "reason": "one sentence on what you extracted"
}

Extraction targets:
- main_text    : primary readable content only, no navigation/header/footer/ads
- links        : all URLs found, one per line as "anchor text: url"
- summary      : concise 2-3 sentence summary of the document
- code_blocks  : all code snippets preserving formatting, separated by ---
- (empty)      : extract all meaningful structured content, preserving sections"""

_HTML_ENTITIES = [
    ("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
    ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
    ("&apos;", "'"),
]


def _clean_html(html: str) -> str:
    """
    Deterministic HTML cleanup.
    Operation order:
      1. remove script/style (including content)
      2. convert <a href> to "text [url]" — preserves URLs for the LLM
      3. mark <pre>/<code> blocks with newlines — preserves code structure
      4. remove all remaining tags
      5. decode HTML entities
      6. normalize whitespace
    """
    # 1. Remove script and style (including content)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)

    # 2. Convert anchor tags to "text [url]" before stripping
    def _anchor(m):
        inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        url   = m.group(1).strip()
        return f"{inner} [{url}]" if inner else f"[{url}]"

    html = re.sub(
        r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        _anchor,
        html, flags=re.DOTALL | re.IGNORECASE,
    )

    # 3. Convert pre/code to readable blocks (newlines in place of tags)
    html = re.sub(r"<pre[^>]*>",  "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"</pre>",       "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"<code[^>]*>",  "\n",  html, flags=re.IGNORECASE)
    html = re.sub(r"</code>",      "\n",  html, flags=re.IGNORECASE)

    # 4. Remove all remaining HTML tags
    html = re.sub(r"<[^>]+>", " ", html)

    # 5. Decode common entities
    for entity, char in _HTML_ENTITIES:
        html = html.replace(entity, char)

    # 6. Normalize whitespace
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _detect_type(content: str) -> str:
    """Auto-detect document type from the first 500 chars."""
    sample = content[:500]
    if re.search(r"<[a-z]+[\s>]", sample, re.IGNORECASE):
        return "html"
    if re.search(r"^#{1,6}\s", sample, re.MULTILINE):
        return "markdown"
    return "plain"


def parse_document(content: str, doc_type: str = "auto",
                   extract: str = "", max_input_chars: int = 20_000) -> str:
    """
    [H] Extract structure from HTML or raw text.
    Deterministic mechanism: strip HTML, normalize whitespace.
    LLM judgment: extracts the requested content from the cleaned text.

    content        : raw content (e.g. output of web_fetch)
    doc_type       : "html" | "markdown" | "plain" | "auto"
    extract        : "main_text" | "links" | "summary" | "code_blocks" | ""
    max_input_chars: truncates input to the model to avoid exceeding context
    Returns        : extracted text or "ERROR: ..."
    """
    if not content or not content.strip():
        return "ERROR: empty content"

    # 1. Auto-detect and pre-clean [D]
    detected = _detect_type(content) if doc_type == "auto" else doc_type
    cleaned  = _clean_html(content) if detected == "html" else content.strip()

    # Truncate if too long for the context window
    if len(cleaned) > max_input_chars:
        cleaned = cleaned[:max_input_chars] + "\n... [truncated]"

    # 2. Ask the LLM to extract the content [H]
    target_desc = extract if extract else "all meaningful content"
    user_msg = (
        f"Document type: {detected}\n"
        f"Extract: {target_desc}\n\n"
        f"Document text:\n{cleaned}"
    )

    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
        )
        result = extract_json(raw)
    except Exception as e:
        return f"ERROR: LLM call failed — {e}"

    # 3. Return the result [D]
    return result.get("result", "ERROR: LLM returned no result")
