# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# llm_client.py — calls the LLM backend and returns text.
# Completely domain-agnostic: knows only HTTP and the OpenAI-compatible API.
#
# Single transport: any OpenAI-compatible endpoint at
#   POST {BASE_URL}/chat/completions
# where BASE_URL ends in /v1 (llama.cpp server, LM Studio, Ollama `/v1`,
# vLLM, OpenAI, Groq, OpenRouter, DeepSeek, LiteLLM...). The code only ever
# appends /chat/completions (blocking) or relies on stream=True (SSE), and
# GET {BASE_URL}/models for the health check. No vendor-specific routes.
#
# Calls may override base_url / api_key per-call (used by the `code` skill to
# target a different model server). Without override, values come from config,
# which respect environment variables.

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


# Default base URL when none is configured: llama.cpp server's default port,
# with the /v1 suffix the OpenAI-compatible API requires.
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"


# ── Endpoint resolution ────────────────────────────────────────────────────────

def _resolved_endpoint(base_url, api_key):
    """Resolve (base_url, api_key) applying fallback from config.

    base_url is the OpenAI-compatible base that ends in /v1; the caller code
    appends /chat/completions or /models. api_key is optional (local servers
    usually need none)."""
    url = (base_url or config.LLM_BASE_URL or DEFAULT_BASE_URL).rstrip("/")
    key = api_key or config.LLM_API_KEY
    return url, key


def ping_models(base_url=None, api_key=None, timeout=5):
    """Health check: GET {BASE_URL}/models on the OpenAI-compatible endpoint.

    Returns (ok: bool, detail: str). Never raises — used at startup and by the
    configure step to verify the backend is reachable before launching.

    Side effect: on success it resolves the model the endpoint is ACTUALLY
    serving (llama.cpp reports the loaded model in /models) into
    config.SERVED_MODEL, so banners and provenance can show the truth instead
    of trusting the DEFAULT_MODEL label — which lies as soon as you swap
    models on the same port."""
    url, key = _resolved_endpoint(base_url, api_key)
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        resp = requests.get(f"{url}/models", headers=headers, timeout=timeout)
    except Exception as e:
        return False, f"cannot reach {url}/models — {e}"
    if resp.status_code != 200:
        return False, f"{url}/models returned HTTP {resp.status_code}"
    served = ""
    try:
        data = (resp.json() or {}).get("data") or []
        if data:
            raw = str(data[0].get("id", ""))
            served = raw.replace("\\", "/").split("/")[-1]
            for ext in (".gguf", ".bin"):
                if served.lower().endswith(ext):
                    served = served[: -len(ext)]
            if served:
                config.SERVED_MODEL = served
    except Exception:
        pass
    return True, f"{url} reachable" + (f" · serving {served}" if served else "")


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

    The waiting spinner shows the model the endpoint actually serves (when
    known) and a live elapsed counter, so a long call is visibly alive."""
    disp = getattr(config, "SERVED_MODEL", "") or label
    last = None
    for attempt in range(5):
        if stop_event is not None and stop_event.is_set():
            raise LLMInterrupted("LLM call aborted by stop signal")
        start = time.time()
        holder: dict = {"resp": None, "exc": None}

        def _worker():
            try:
                holder["resp"] = _interruptible_post(
                    url, headers, payload, timeout, stop_event)
            except Exception as e:
                holder["exc"] = e

        with _console.status(
            f"[bold cyan]{disp} is thinking...[/bold cyan]",
            spinner="dots",
        ) as status:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            while t.is_alive():
                t.join(timeout=0.5)
                status.update(
                    f"[bold cyan]{disp} is thinking... "
                    f"{int(time.time() - start)}s[/bold cyan]")
        if holder["exc"] is not None:
            raise holder["exc"]
        last = holder["resp"]
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

# Stats of the most recent blocking call: {"prompt","completion","total",
# "seconds","model"}. Read by renderers (batch) to show per-step token counts,
# speed and context usage. Best-effort — empty when the backend sends no usage.
LAST_STATS: dict = {}

# Set once if the endpoint rejects a json_schema response_format, so a server
# without structured output costs one failed request per process instead of
# one per faculty call. Mirrors _TOOLS_UNSUPPORTED on the action channel.
_SCHEMA_UNSUPPORTED = [False]


def _call_openai_compatible(messages, model, temperature, max_tokens, timeout, base_url, api_key, stop_event=None, response_schema=None):
    """Standard OpenAI /chat/completions — works with Groq, Ollama, vLLM, etc."""
    global LAST_STATS
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    if response_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": response_schema.get("__name__", "reply"),
                            "schema": {k: v for k, v in response_schema.items()
                                       if k != "__name__"},
                            "strict": True},
        }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    t0     = time.time()
    resp   = _post_with_retry(f"{base_url}/chat/completions", headers, payload, timeout, model, stop_event)
    dt     = time.time() - t0
    data   = resp.json()
    usage  = data.get("usage") or {}
    LAST_STATS = {
        "prompt":     usage.get("prompt_tokens", 0) or 0,
        "completion": usage.get("completion_tokens", 0) or 0,
        "total":      usage.get("total_tokens", 0) or 0,
        "seconds":    dt,
        "model":      getattr(config, "SERVED_MODEL", "") or model,
    }
    choice = data["choices"][0]
    msg    = choice.get("message", {})
    finish = choice.get("finish_reason", "")
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
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


# ── Public API ─────────────────────────────────────────────────────────────────

class ToolsUnsupported(Exception):
    """The endpoint would not accept a tools request.

    Raised so a caller can fall back to the text protocol instead of failing:
    tool calling is a recent llama.cpp/OpenAI-compatible feature and Pragma
    must keep working against servers that lack it.
    """


def call_llm_tools(messages, tools, model=None, temperature=None,
                   max_tokens=None, timeout=None, base_url=None, api_key=None,
                   stop_event=None, tool_choice="auto"):
    """Ask the model to choose a tool, and read the choice as structured data.

    The counterpart of call_llm() for the ReAct action channel. The difference
    is not the transport but the guarantee: when a server compiles `tools`
    into a grammar, the arguments are constrained during sampling, so
    malformed or truncated arguments cannot be produced at all. call_llm()
    keeps its text contract and its callers — the memory faculties among them
    — untouched.

    Returns {"content": str, "tool_calls": [{"id", "name", "arguments"}],
             "finish_reason": str}, with `arguments` already decoded to a dict.

    Raises ToolsUnsupported if the endpoint rejects the request in a way that
    indicates it does not implement tools.
    """
    import json as _json

    model       = model or config.DEFAULT_MODEL
    temperature = config.DEFAULT_TEMPERATURE if temperature is None else temperature
    max_tokens  = max_tokens or config.MAX_TOKENS
    timeout     = timeout or config.TIMEOUT
    base_url, api_key = _resolved_endpoint(base_url, api_key)

    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "tools":       tools,
        "tool_choice": tool_choice,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    global LAST_STATS
    t0 = time.time()
    try:
        resp = _post_with_retry(f"{base_url}/chat/completions", headers,
                                payload, timeout, model, stop_event)
    except LLMInterrupted:
        raise
    except Exception as e:
        # A 400/422 on a payload that only differs by `tools` is the endpoint
        # telling us it does not support them.
        msg = str(e).lower()
        if any(s in msg for s in ("400", "422", "tools", "tool_choice",
                                  "unknown field", "unsupported")):
            raise ToolsUnsupported(str(e)[:300]) from e
        raise
    dt = time.time() - t0

    data  = resp.json()
    usage = data.get("usage") or {}
    LAST_STATS = {
        "prompt":     usage.get("prompt_tokens", 0) or 0,
        "completion": usage.get("completion_tokens", 0) or 0,
        "total":      usage.get("total_tokens", 0) or 0,
        "seconds":    dt,
        "model":      getattr(config, "SERVED_MODEL", "") or model,
    }

    choice = (data.get("choices") or [{}])[0]
    msg    = choice.get("message") or {}
    calls  = []
    for tc in (msg.get("tool_calls") or []):
        fn   = tc.get("function") or {}
        raw  = fn.get("arguments")
        # Servers send arguments as a JSON string; some send an object.
        if isinstance(raw, str):
            try:
                args = _json.loads(raw)
            except Exception:
                # Grammar-constrained output should make this impossible;
                # if it happens, hand back the raw text so the caller can
                # report it rather than silently dropping the call.
                args = {"__unparsed_arguments__": raw}
        elif isinstance(raw, dict):
            args = raw
        else:
            args = {}
        calls.append({"id": tc.get("id") or "",
                      "name": fn.get("name") or "",
                      "arguments": args})

    return {
        "content":       (msg.get("content") or "").strip(),
        "reasoning":     (msg.get("reasoning_content") or "").strip(),
        "tool_calls":    calls,
        "finish_reason": choice.get("finish_reason", ""),
    }


def call_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
             base_url=None, api_key=None, stop_event=None, response_schema=None):
    """
    Send messages to the OpenAI-compatible endpoint and return the response text.

    messages    : list [{role, content}, ...] in OpenAI style
    model       : model name (default config.DEFAULT_MODEL)
    temperature : default config.DEFAULT_TEMPERATURE
    max_tokens  : default config.MAX_TOKENS
    timeout     : default config.TIMEOUT
    base_url    : OpenAI-compatible base ending in /v1 (default from config)
    api_key     : API key, optional for local servers   (default from config)
    response_schema : JSON Schema the reply must satisfy. HONOURED ONLY on the
                  native protocol, where a server that compiles it into a
                  grammar makes a malformed reply impossible to generate
                  rather than merely detectable. On the text protocol it is
                  ignored, so the frozen corpus stays reproducible. An
                  optional "__name__" key names the schema and is stripped
                  before sending.

    Hits POST {base_url}/chat/completions. Automatic retry on 502.
    """
    if model       is None: model       = config.DEFAULT_MODEL
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    # The schema rides the same switch as the action channel: one flag decides
    # whether this run is constrained end to end or reproduces the old one.
    # MEMORY_SCHEMA=0 additionally ablates the schema while LEAVING the action
    # channel native, which is the only way to attribute a difference in what
    # memory holds to the constraint rather than to the channel.
    if (getattr(config, "LLM_TOOL_PROTOCOL", "text") != "native"
            or not getattr(config, "MEMORY_SCHEMA", True)
            or _SCHEMA_UNSUPPORTED[0]):
        response_schema = None

    url, key = _resolved_endpoint(base_url, api_key)
    try:
        text, finish = _call_openai_compatible(
            messages, model, temperature, max_tokens, timeout, url, key,
            stop_event, response_schema,
        )
    except LLMInterrupted:
        raise
    except Exception as e:
        # An endpoint that does not implement json_schema rejects the payload
        # outright. Degrade for the rest of the process rather than failing a
        # faculty: the reply is still parsed leniently downstream, exactly as
        # it was before schemas existed.
        msg = str(e).lower()
        if response_schema and any(s in msg for s in (
                "400", "422", "response_format", "json_schema", "schema",
                "unknown field", "unsupported")):
            _SCHEMA_UNSUPPORTED[0] = True
            if config.DEBUG:
                print(f"[llm] endpoint rejected response_format ({str(e)[:120]}); "
                      f"continuing without schemas.")
            text, finish = _call_openai_compatible(
                messages, model, temperature, max_tokens, timeout, url, key,
                stop_event, None,
            )
        else:
            raise

    # Salvage partial text on length truncation if possible.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    if not text:
        raise RuntimeError("The model returned an empty response.")

    return text


def stream_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
               base_url=None, api_key=None, stop_event=None,
               on_token=None, on_reasoning=None):
    """
    Like call_llm but calls on_token(chunk: str) for each text fragment as it
    arrives over SSE. Returns the complete response text when done.
    """
    if model       is None: model       = config.DEFAULT_MODEL
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    url, key = _resolved_endpoint(base_url, api_key)
    return _stream_openai_compatible(
        messages, model, temperature, max_tokens, timeout,
        url, key, stop_event, on_token, on_reasoning,
    )


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
