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

import time
import requests
from rich.console import Console

import config

_console = Console()

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
        # Internal provider — requires BACKEND_URL and BACKEND_KEY in environment
        url = (base_url or config.LLM_BASE_URL or config.BACKEND_URL).rstrip("/")
        key = api_key  or config.LLM_API_KEY  or config.BACKEND_KEY
    else:  # "openai" or any compatible endpoint
        url = (base_url or config.LLM_BASE_URL or "").rstrip("/")
        key = api_key  or config.LLM_API_KEY

    return p, url, key


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _post_with_retry(url, headers, payload, timeout, label):
    """POST with retry on 502 (backoff 30/60/90/120s). Returns response."""
    last = None
    for attempt in range(5):
        with _console.status(
            f"[bold cyan]{label} is thinking...[/bold cyan]",
            spinner="dots",
        ):
            last = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if last.status_code != 502:
            break
        wait = 30 * (attempt + 1)
        _console.print(
            f"[yellow][llm_client] 502 — waiting {wait}s and retrying "
            f"({attempt + 1}/5)...[/yellow]"
        )
        time.sleep(wait)
    last.raise_for_status()
    return last


# ── Provider backends ──────────────────────────────────────────────────────────

def _call_backend(messages, model, temperature, max_tokens, timeout, base_url, api_key):
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
    resp   = _post_with_retry(f"{base_url}/llm", headers, payload, timeout, model)
    data   = resp.json()
    msg    = data["raw"]["choices"][0]["message"]
    finish = data["raw"]["choices"][0].get("finish_reason", "")
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, finish


def _call_openai_compatible(messages, model, temperature, max_tokens, timeout, base_url, api_key):
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
    resp   = _post_with_retry(f"{base_url}/chat/completions", headers, payload, timeout, model)
    data   = resp.json()
    choice = data["choices"][0]
    msg    = choice.get("message", {})
    finish = choice.get("finish_reason", "")
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, finish


def _call_anthropic(messages, model, temperature, max_tokens, timeout, base_url, api_key):
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

    resp = _post_with_retry(f"{base_url}/v1/messages", headers, payload, timeout, model)
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


# ── Public API ─────────────────────────────────────────────────────────────────

def call_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
             provider=None, base_url=None, api_key=None):
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
        text, finish = _call_backend(messages, model, temperature, max_tokens, timeout, url, key)
    elif prov == "openai":
        text, finish = _call_openai_compatible(messages, model, temperature, max_tokens, timeout, url, key)
    elif prov == "anthropic":
        text, finish = _call_anthropic(messages, model, temperature, max_tokens, timeout, url, key)
    else:
        raise ValueError(
            f"Unknown LLM provider: {prov!r}. "
            f"Use 'backend', 'openai' or 'anthropic'."
        )

    if finish == "length":
        raise RuntimeError(
            f"Response truncated (finish_reason=length). Increase max_tokens. "
            f"Partial text: {text[:100]!r}"
        )
    if not text:
        raise RuntimeError("The model returned an empty response.")

    return text


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
