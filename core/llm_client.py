# llm_client.py — calls the LLM backend and returns text.
# Completely domain-agnostic: knows only HTTP and three providers.
#
# Supported providers:
#   "backend"   — custom proxy at /llm with schema {raw:{choices:[{message:{content}}]}}
#   "openai"    — any OpenAI-compatible endpoint at /chat/completions
#                 (OpenAI, Groq, OpenRouter, Together, DeepSeek, Mistral,
#                  Ollama `/v1`, vLLM, LM Studio, llama.cpp server, LiteLLM...)
#   "anthropic" — native Anthropic API at /v1/messages
#                 (header x-api-key, response schema {content:[{type:"text",text:"..."}]})
#
# All calls can override provider / base_url / api_key by passing the
# corresponding kwargs. Without override, values from config are used,
# which in turn respect environment variables.

import threading
import time
import requests
from rich.console import Console

import config

_console = Console()


class LLMInterrupted(Exception):
    """Raised when the LLM HTTP call is aborted via stop_event."""
    pass


class LLMLooped(Exception):
    """Raised when the watchdog detects the model is repeating itself
    inside the <think> block — i.e. the reasoning_content stream is
    producing the same paragraph over and over without converging.
    The caller (agent loop) catches this and injects a recovery hint
    so the model can change strategy on the next turn."""
    pass


# Marker prepended to text that came back as a truncated partial. The agent
# loop strips it back off but uses its presence to know the response was
# cut mid-stream — useful for synthesizing a 'this was truncated' note
# inside the conclusion when no JSON could be parsed.
TRUNCATION_PARTIAL_MARKER = "__PRAGMA_TRUNCATED_PARTIAL__"


def _on_length_finish(text: str, finish: str):
    """Centralized handling of finish_reason=length.

    Old behavior: ALWAYS raise. The partial text was lost — including
    cases where the model had emitted enough content to extract a
    conclusion / answer.

    New behavior:
      - If we have a substantive partial (> 50 chars), tag it with a
        marker and return it. extract_json / react.py recovery can
        salvage it (parse as JSON if balanced, json_repair if close,
        wrap as plain-text conclusion if neither).
      - If the partial is empty / trivial, raise as before — there is
        nothing to salvage.

    Returns the text to return from the streaming function, or raises
    RuntimeError when truly nothing can be saved.
    """
    if finish != "length":
        return text
    if text and len(text) > 50:
        return TRUNCATION_PARTIAL_MARKER + text
    raise RuntimeError(
        f"Response truncated (finish_reason=length). Partial: {text[:100]!r}"
    )


class _ReasoningLoopGuard:
    """Repetition detector for streaming reasoning text.

    Approach: every `check_every` characters of accumulated reasoning, take
    the trailing `window` chars and count how many times that exact string
    appears in the recent buffer (`scope` chars). When the count reaches
    `threshold`, the model is repeating itself and we abort.

    Counting via str.count is O(scope) per check — bounded, since `scope`
    is clamped (defaults to 8000 chars). Across the whole stream the total
    cost stays linear in the reasoning length.

    Why not fingerprint-and-hash: the loop period rarely matches the
    sampling period, so identical text sampled at different offsets gives
    different fingerprints and the loop goes undetected. Counting the
    actual trailing substring is offset-agnostic.
    """

    __slots__ = ("window", "check_every", "threshold", "scope",
                 "_next_sample_at", "_disabled")

    def __init__(self, window: int = 200, check_every: int = 400,
                 threshold: int = 3, scope: int = 8000,
                 enabled: bool = True):
        self.window          = window
        self.check_every     = check_every
        self.threshold       = threshold
        self.scope           = scope
        self._next_sample_at = check_every
        self._disabled       = (not enabled) or window <= 0 or threshold < 2

    def observe(self, chunk: str, buf: str) -> None:
        """Called after each reasoning chunk. `buf` is the full accumulated
        reasoning so far. Raises LLMLooped when a loop is detected."""
        if self._disabled:
            return
        total = len(buf)
        if total < self._next_sample_at or total < self.window * self.threshold:
            return
        self._next_sample_at = total + self.check_every
        tail  = buf[-self.window:]
        # Bound the search range so cost stays O(scope) per check.
        view  = buf[-self.scope:] if total > self.scope else buf
        n     = view.count(tail)
        if n >= self.threshold:
            raise LLMLooped(
                f"Reasoning loop detected: the trailing {self.window}-char "
                f"window appears {n} times in the last {len(view)} chars."
            )


def _make_loop_guard():
    """Build a watchdog using the current config values."""
    import config as _cfg
    return _ReasoningLoopGuard(
        window      = getattr(_cfg, "REASONING_LOOP_WINDOW", 200),
        check_every = getattr(_cfg, "REASONING_LOOP_CHECK_EVERY", 400),
        threshold   = getattr(_cfg, "REASONING_LOOP_THRESHOLD", 3),
        enabled     = getattr(_cfg, "REASONING_LOOP_ENABLED", True),
    )


ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION  = "2023-06-01"


# ── Endpoint resolution ────────────────────────────────────────────────────────

def _resolved_endpoint(provider, base_url, api_key):
    """Resolve (provider, base_url, api_key) applying fallback from config."""
    p = provider or config.LLM_PROVIDER or "openai"

    if p == "anthropic":
        url = (base_url or config.LLM_BASE_URL or ANTHROPIC_BASE_URL).rstrip("/")
        key = api_key  or config.LLM_API_KEY
    elif p == "backend":
        # Internal provider — uses BACKEND_URL/BACKEND_KEY, NOT the openai-oriented vars
        url = (base_url or config.BACKEND_URL).rstrip("/")
        key = api_key  or config.BACKEND_KEY
    else:  # "openai" or any compatible endpoint
        url = (base_url or config.LLM_BASE_URL or "http://localhost:11434/v1").rstrip("/")
        key = api_key  or config.LLM_API_KEY

    return p, url, key


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _interruptible_post(url, headers, payload, timeout, stop_event):
    """POST that aborts mid-flight when stop_event is set.

    Runs the request in a daemon thread; the main thread polls stop_event
    every 100ms and, if set, closes the underlying Session — that forces
    the in-flight HTTP request to raise ConnectionError, which we wrap
    as LLMInterrupted so the agent loop can react cleanly.
    """
    if stop_event is None:
        return requests.post(url, headers=headers, json=payload, timeout=timeout)

    session = requests.Session()
    holder: dict = {"resp": None, "exc": None}

    def _do():
        try:
            holder["resp"] = session.post(
                url, headers=headers, json=payload, timeout=timeout
            )
        except Exception as e:
            holder["exc"] = e
        finally:
            try: session.close()
            except Exception: pass

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    while t.is_alive():
        if stop_event.is_set():
            try: session.close()  # forces the in-flight request to abort
            except Exception: pass
            t.join(timeout=2)
            raise LLMInterrupted("LLM call aborted by stop signal")
        t.join(timeout=0.1)

    if holder["exc"] is not None:
        # Closed-by-stop manifests as ConnectionError after the loop above.
        if stop_event.is_set():
            raise LLMInterrupted("LLM call aborted by stop signal")
        raise holder["exc"]
    return holder["resp"]


def _post_with_retry(url, headers, payload, timeout, label, stop_event=None):
    """POST with retry on 502 (backoff 30/60/90/120s). Returns response.

    If stop_event is provided and gets set, the call is aborted via
    LLMInterrupted at the next check (mid-request or between retries).
    """
    last = None
    for attempt in range(5):
        if stop_event is not None and stop_event.is_set():
            raise LLMInterrupted("LLM call aborted by stop signal")
        with _console.status(
            f"[bold cyan]{label} is thinking...[/bold cyan]",
            spinner="dots",
        ):
            last = _interruptible_post(url, headers, payload, timeout, stop_event)
        if last.status_code != 502:
            break
        wait = 30 * (attempt + 1)
        _console.print(
            f"[yellow][llm_client] 502 — waiting {wait}s and retrying "
            f"({attempt + 1}/5)...[/yellow]"
        )
        # Sleep in small slices so stop is responsive during backoff
        slept = 0.0
        while slept < wait:
            if stop_event is not None and stop_event.is_set():
                raise LLMInterrupted("LLM call aborted by stop signal")
            time.sleep(min(0.2, wait - slept))
            slept += 0.2
    last.raise_for_status()
    return last


# ── Provider backends ──────────────────────────────────────────────────────────

def _call_backend(messages, model, temperature, max_tokens, timeout, base_url, api_key, stop_event=None):
    """Custom proxy with schema {raw:{choices:[{message:{content}}]}}."""
    payload = {
        "messages":    messages,
        "model":       model,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    resp   = _post_with_retry(f"{base_url}/llm", headers, payload, timeout, model, stop_event)
    data   = resp.json()
    msg    = data["raw"]["choices"][0]["message"]
    finish = data["raw"]["choices"][0].get("finish_reason", "")
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, finish


def _call_openai_compatible(messages, model, temperature, max_tokens, timeout, base_url, api_key, stop_event=None):
    """Standard OpenAI /chat/completions — works with Groq, Ollama, vLLM, etc."""
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp   = _post_with_retry(f"{base_url}/chat/completions", headers, payload, timeout, model, stop_event)
    data   = resp.json()
    choice = data["choices"][0]
    msg    = choice.get("message", {})
    finish = choice.get("finish_reason", "")
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, finish


def _call_anthropic(messages, model, temperature, max_tokens, timeout, base_url, api_key, stop_event=None):
    """Native Anthropic API at /v1/messages.

    The Anthropic schema separates the system prompt from the rest:
      { model, system, messages:[{role,content}], max_tokens, temperature }
    The system prompt is the first message with role=="system" (if present).
    """
    # Separate system prompt (Anthropic wants a dedicated field, not inline)
    system_content = ""
    user_messages  = []
    for m in messages:
        if m.get("role") == "system" and not user_messages:
            system_content = m.get("content", "")
        else:
            # Anthropic only accepts role "user" | "assistant"
            role = m.get("role", "user")
            if role not in ("user", "assistant"):
                role = "user"
            user_messages.append({"role": role, "content": m.get("content", "")})

    # Anthropic requires the first message to be "user"
    if not user_messages:
        user_messages = [{"role": "user", "content": ""}]

    payload: dict = {
        "model":       model,
        "messages":    user_messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    if system_content:
        payload["system"] = system_content

    headers = {
        "Content-Type":    "application/json",
        "x-api-key":       api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    resp = _post_with_retry(f"{base_url}/v1/messages", headers, payload, timeout, model, stop_event)
    data = resp.json()

    # Response: {content:[{type:"text", text:"..."}], stop_reason, ...}
    content_blocks = data.get("content", [])
    text = "".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    ).strip()

    # Anthropic uses "stop_reason" (e.g. "end_turn", "max_tokens")
    finish = data.get("stop_reason", "")
    if finish == "max_tokens":
        finish = "length"

    return text, finish


# ── Streaming helpers ──────────────────────────────────────────────────────────

def _stream_openai_compatible(messages, model, temperature, max_tokens, timeout,
                               base_url, api_key, stop_event, on_token,
                               on_reasoning=None):
    """Stream from an OpenAI-compatible /chat/completions endpoint (SSE)."""
    import json as _json
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      True,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    text = ""
    reasoning_buf = ""
    finish = ""
    guard = _make_loop_guard()
    with requests.Session() as session:
        with session.post(
            f"{base_url}/chat/completions",
            headers=headers, json=payload,
            stream=True, timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event and stop_event.is_set():
                    raise LLMInterrupted("LLM call aborted by stop signal")
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data)
                except Exception:
                    continue
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or ""
                content   = delta.get("content") or ""
                if reasoning:
                    reasoning_buf += reasoning
                    if on_reasoning:
                        on_reasoning(reasoning)
                    guard.observe(reasoning, reasoning_buf)
                if content:
                    text += content
                    if on_token:
                        on_token(content)
                fin = choice.get("finish_reason")
                if fin:
                    finish = fin

    # Salvage partial text on length truncation if possible. See _on_length_finish.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    # Fallback: some reasoning models (e.g. Qwen3) emit the entire answer
    # inside the <think> block as reasoning_content and never produce content.
    # Use the reasoning buffer as the response text in that case.
    if not text and reasoning_buf:
        text = reasoning_buf
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text


def _stream_anthropic(messages, model, temperature, max_tokens, timeout,
                       base_url, api_key, stop_event, on_token,
                       on_reasoning=None):
    """Stream from the native Anthropic API (SSE)."""
    import json as _json

    system_content = ""
    user_messages = []
    for m in messages:
        if m.get("role") == "system" and not user_messages:
            system_content = m.get("content", "")
        else:
            role = m.get("role", "user")
            if role not in ("user", "assistant"):
                role = "user"
            user_messages.append({"role": role, "content": m.get("content", "")})
    if not user_messages:
        user_messages = [{"role": "user", "content": ""}]

    payload = {
        "model":       model,
        "messages":    user_messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
        "stream":      True,
    }
    if system_content:
        payload["system"] = system_content

    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    text = ""
    reasoning_buf = ""
    finish = ""
    guard = _make_loop_guard()
    with requests.Session() as session:
        with session.post(
            f"{base_url}/v1/messages",
            headers=headers, json=payload,
            stream=True, timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event and stop_event.is_set():
                    raise LLMInterrupted("LLM call aborted by stop signal")
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                try:
                    ev = _json.loads(data)
                except Exception:
                    continue
                ev_type = ev.get("type", "")
                if ev_type == "content_block_delta":
                    delta = ev.get("delta", {})
                    if delta.get("type") == "thinking_delta":
                        reasoning = delta.get("thinking", "")
                        if reasoning:
                            reasoning_buf += reasoning
                            if on_reasoning:
                                on_reasoning(reasoning)
                            guard.observe(reasoning, reasoning_buf)
                    elif delta.get("type") == "text_delta":
                        content = delta.get("text", "")
                        if content:
                            text += content
                            if on_token:
                                on_token(content)
                elif ev_type == "message_delta":
                    if ev.get("delta", {}).get("stop_reason") == "max_tokens":
                        finish = "length"

    # Salvage partial text on length truncation if possible. See _on_length_finish.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    if not text and reasoning_buf:
        text = reasoning_buf
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text


def _stream_backend(messages, model, temperature, max_tokens, timeout,
                    base_url, api_key, stop_event, on_token, on_reasoning=None):
    """Stream from the backend's /llm/stream SSE endpoint.

    The backend proxies llama.cpp's SSE verbatim, so the format is identical
    to a standard OpenAI /chat/completions stream.
    """
    import json as _json
    payload = {
        "messages":    messages,
        "model":       model,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    text          = ""
    reasoning_buf = ""
    finish        = ""
    guard         = _make_loop_guard()
    with requests.Session() as session:
        with session.post(
            f"{base_url}/llm/stream",
            headers=headers, json=payload,
            stream=True, timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event and stop_event.is_set():
                    raise LLMInterrupted("LLM call aborted by stop signal")
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data)
                except Exception:
                    continue
                choice    = chunk.get("choices", [{}])[0]
                delta     = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or ""
                content   = delta.get("content") or ""
                if reasoning:
                    reasoning_buf += reasoning
                    if on_reasoning:
                        on_reasoning(reasoning)
                    guard.observe(reasoning, reasoning_buf)
                if content:
                    text += content
                    if on_token:
                        on_token(content)
                fin = choice.get("finish_reason")
                if fin:
                    finish = fin

    # Salvage partial text on length truncation if possible. See _on_length_finish.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    # Fallback: some reasoning models (e.g. Qwen3) emit the entire answer
    # inside the <think> block as reasoning_content and never produce content.
    # Use the reasoning buffer as the response text in that case.
    if not text and reasoning_buf:
        text = reasoning_buf
    if not text:
        raise RuntimeError("The model returned an empty response.")
    return text


# ── Public API ─────────────────────────────────────────────────────────────────

def call_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
             provider=None, base_url=None, api_key=None, stop_event=None):
    """
    Send messages to the model and return the response as a string.

    messages    : list [{role, content}, ...] in OpenAI style
    model       : model name (default config.DEFAULT_MODEL)
    temperature : default config.DEFAULT_TEMPERATURE
    max_tokens  : default config.MAX_TOKENS
    timeout     : default config.TIMEOUT
    provider    : "backend" | "openai" | "anthropic"  (default config.LLM_PROVIDER)
    base_url    : service base URL                     (default from config)
    api_key     : API key                              (default from config)

    Automatic retry on 502: backoff 30/60/90/120s, then raises.
    """
    if model       is None: model       = config.DEFAULT_MODEL
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    prov, url, key = _resolved_endpoint(provider, base_url, api_key)

    if prov == "backend":
        text, finish = _call_backend(messages, model, temperature, max_tokens, timeout, url, key, stop_event)
    elif prov == "openai":
        text, finish = _call_openai_compatible(messages, model, temperature, max_tokens, timeout, url, key, stop_event)
    elif prov == "anthropic":
        text, finish = _call_anthropic(messages, model, temperature, max_tokens, timeout, url, key, stop_event)
    else:
        raise ValueError(
            f"Unknown LLM provider: {prov!r}. "
            f"Use 'backend', 'openai' or 'anthropic'."
        )

    # Salvage partial text on length truncation if possible.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    if not text:
        raise RuntimeError("The model returned an empty response.")

    return text


def stream_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
               provider=None, base_url=None, api_key=None, stop_event=None,
               on_token=None, on_reasoning=None):
    """
    Like call_llm but calls on_token(chunk: str) for each text fragment as it arrives.
    Returns the complete response text when done.

    The 'backend' provider does not support SSE streaming — it falls back to a
    regular call_llm and invokes on_token once with the full response.
    """
    if model       is None: model       = config.DEFAULT_MODEL
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    prov, url, key = _resolved_endpoint(provider, base_url, api_key)

    if prov == "backend":
        # Try the SSE streaming endpoint /llm/stream first.
        # Fall back to the blocking /llm call if the endpoint is not available
        # (404) so older deployments continue to work unchanged.
        try:
            return _stream_backend(
                messages, model, temperature, max_tokens, timeout,
                url, key, stop_event, on_token, on_reasoning,
            )
        except requests.HTTPError as _e:
            if _e.response is not None and _e.response.status_code == 404:
                if config.DEBUG:
                    _console.print("[yellow]/llm/stream not found — falling back to /llm[/yellow]")
            else:
                raise
        # Fallback: blocking call + single on_token with thought preview
        text, finish = _call_backend(
            messages, model, temperature, max_tokens, timeout, url, key, stop_event
        )
        # Salvage partial text on length truncation if possible.
        text = _on_length_finish(text, finish)
        finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
        if not text:
            raise RuntimeError("The model returned an empty response.")
        if on_token:
            import json as _json
            try:
                _preview = _json.loads(text).get("thought") or text
            except Exception:
                _preview = text
            on_token(_preview)
        return text
    elif prov == "openai":
        return _stream_openai_compatible(
            messages, model, temperature, max_tokens, timeout,
            url, key, stop_event, on_token, on_reasoning,
        )
    elif prov == "anthropic":
        return _stream_anthropic(
            messages, model, temperature, max_tokens, timeout,
            url, key, stop_event, on_token, on_reasoning,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {prov!r}.")


if __name__ == "__main__":
    test_messages = [
        {"role": "system", "content": "You are a concise assistant."},
        {"role": "user",   "content": "Reply only with: CONNECTION OK"},
    ]
    try:
        r = call_llm(test_messages, temperature=0.0, max_tokens=512)
        print(f"PASS — {r}")
    except Exception as e:
        print(f"FAIL — {e}")
