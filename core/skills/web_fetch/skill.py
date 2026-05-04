from __future__ import annotations

import requests


def web_fetch(url: str, timeout: int = 30,
              max_chars: int = 50_000) -> str:
    """
    HTTP GET a URL. Returns the raw content (text).
    max_chars: truncates the body if too long (default 50k chars).
    """
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "homo-agens/agent-baseline"},
        )
        resp.raise_for_status()
        body = resp.text
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n... (truncated at {max_chars} chars)"
        return body
    except requests.HTTPError as e:
        return f"HTTP ERROR {e.response.status_code}: {e}"
    except requests.ConnectionError as e:
        return f"CONNECTION ERROR: {e}"
    except requests.Timeout:
        return f"TIMEOUT after {timeout}s: {url}"
    except Exception as e:
        return f"ERROR: {e}"
