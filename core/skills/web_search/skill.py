from __future__ import annotations

import config


def web_search(query: str, num_results: int = 10,
               engine: str = "duckduckgo") -> str:
    """
    [G] Query a search engine. Returns ranked snippets and URLs.
    engine : "duckduckgo" (default, no API key required) | "serper" | "brave"

    Note: optimal query formulation may require an upstream llm_invoke()
    by the calling agent (judgment [H]).
    """
    if engine == "duckduckgo":
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                return (
                    "ERROR: DDGS library not installed. "
                    "Run: pip install ddgs"
                )
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=num_results))
        except Exception as e:
            return f"ERROR: DuckDuckGo search failed — {e}"

    elif engine == "serper":
        api_key = getattr(config, "SERPER_API_KEY", "")
        if not api_key:
            return "ERROR: SERPER_API_KEY not configured in config.py"
        try:
            import requests
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num_results},
                timeout=15,
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
            results = [
                {"title": r.get("title", ""), "href": r.get("link", ""),
                 "body": r.get("snippet", "")}
                for r in organic
            ]
        except Exception as e:
            return f"ERROR: Serper search failed — {e}"

    else:
        return f"ERROR: engine '{engine}' not supported. Use 'duckduckgo' or 'serper'."

    if not results:
        return "NO RESULTS"

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.get('title', '')}] {r.get('href', '')}")
        body = r.get("body", "")
        if body:
            lines.append(f"   {body[:200]}")
        lines.append("")

    return "\n".join(lines).strip()
