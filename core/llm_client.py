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

import sys
import threading
import time
from contextlib import contextmanager

import requests
from rich.console import Console

import config
import endpoints

_console = Console()

# The frames of rich's "dots" spinner. Braille, so a stream that cannot encode
# them is a stream the spinner must not be written to.
_SPINNER_PROBE = "\u2839"


def _can_spin() -> bool:
    """Is there a stream that can actually render a spinner frame?

    Not `isatty`, and not rich's `is_terminal`: on Windows both say yes for a
    process whose stdout is DEVNULL, because NUL is a character device. What
    decides it is the ENCODING. A console-less process opens stdout as cp1252,
    rich falls back to its legacy Windows renderer, and writing U+2839 there
    raises UnicodeEncodeError from inside the LLM call - which every faculty
    catches as its own failure and reports as "unavailable", with no reason.
    Asking the stream whether it can take the character is the honest test,
    and it covers piping a run to a file as well as the background worker.
    """
    try:
        enc = getattr(sys.stdout, "encoding", None)
        if not enc:
            return False
        _SPINNER_PROBE.encode(enc)
        return True
    except Exception:
        return False


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
DEFAULT_BASE_URL = endpoints.DEFAULT_BASE_URL


# ── Endpoint resolution ────────────────────────────────────────────────────────

def current_endpoint() -> "endpoints.Endpoint":
    """The endpoint for whoever is calling: the faculty named on this thread."""
    return endpoints.for_role(endpoints.role_of(current_faculty()))


def resolved_model(model=None) -> str:
    """The model name to put in a request.

    An explicit argument wins, then DEFAULT_MODEL, and an empty DEFAULT_MODEL
    means "whatever the endpoint is serving" - resolved by asking it once and
    reusing the answer. That is the right default for a single-model server:
    llama.cpp ignores the field and serves what is loaded, so a name typed into
    .env is a label that goes stale the moment another model is put on the same
    port, and reading it back as though it were true is how a run gets filed
    under the wrong model.

    Set DEFAULT_MODEL explicitly when the endpoint hosts several and the field
    actually selects one - vLLM with more than one loaded, or a hosted API.
    """
    if model:
        return model
    ep = current_endpoint()
    if ep.model:
        return ep.model
    known = endpoints.state(ep.base_url)
    if not known.served_model:
        try:
            ping_models(ep.base_url, ep.api_key, timeout=5)   # fills served_model
        except Exception:
            pass
    # Empty is a legitimate answer: a server that cannot be reached gets the
    # field omitted rather than a guess, and reports its own error.
    return known.served_model or ""


def served_model(role: str) -> str:
    """The model serving `role`, as its endpoint reports it. For provenance.

    With every role on one server this is the same name for all three. Once
    they are split it is the only way to say which model wrote what: the
    agent's model is not the one that consolidated its session. Falls back to
    the name the catalogue declares, and to "" when neither is known.
    """
    try:
        ep = endpoints.for_role(role)
    except endpoints.EndpointError:
        return ""
    known = endpoints.state(ep.base_url)
    if not known.served_model:
        ping_models(ep.base_url, ep.api_key, timeout=5)
    return known.served_model or ep.model


def _resolved_endpoint(base_url, api_key):
    """Resolve (base_url, api_key): an explicit value wins, then the endpoint
    of the calling role.

    base_url is the OpenAI-compatible base that ends in /v1; the caller code
    appends /chat/completions or /models. api_key is optional (local servers
    usually need none)."""
    ep = current_endpoint()
    url = (base_url or ep.base_url).rstrip("/")
    key = api_key or ep.api_key
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
    try:
        url, key = _resolved_endpoint(base_url, api_key)
    except endpoints.EndpointError as e:
        return False, f"endpoint catalogue - {e}"
    # The quick test first: with nothing listening, a plain GET waits out the
    # operating system's connect retries before failing, and every menu that
    # asks would wait with it.
    if not config.endpoint_reachable(url):
        return False, f"cannot reach {url} - not connected"
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
                endpoints.state(url).served_model = served
                # config.SERVED_MODEL is what the banners show as "talking
                # to", so it names the AGENT's model only. Written for any
                # endpoint, it would say whichever server was pinged last.
                try:
                    if url == endpoints.for_role("agent").base_url:
                        config.SERVED_MODEL = served
                except endpoints.EndpointError:
                    pass
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


# WHO DRAWS THE WAIT - AND THE THINKING. The spinner below is the right thing for a batch run
# and for every faculty called from a script: it says who is thinking and for
# how long, and needs nothing from its caller. A live session owns its screen
# and wants ONE status line for the curator, the agent's steps and the tools
# alike, not this spinner interleaved with its own. So the drawing can be
# handed over: an object with begin(label), tick(label, seconds) and end() is
# told exactly what the spinner would have shown, and the spinner stays off.
# None means the spinner, which is every caller that existed before this.
#
# Optional methods on the same object, for the faculties' streamed calls:
# reasoning(chunk, who) receives their reasoning as it is written,
# answering(chunk, who) their answer as it is written, and
# looped(who, detail) is told when a reasoning went in circles and the call
# was asked again without thinking. The conversation's harness shows the first
# under its status line; the background worker writes both into the job.
STATUS_HOOK = None


def _hook(name):
    return getattr(STATUS_HOOK, name, None) if STATUS_HOOK is not None else None


def _post_with_retry(url, headers, payload, timeout, label, stop_event=None):
    """POST with retry on 502 (backoff 30/60/90/120s). Returns response.

    If stop_event is provided and gets set, the call is aborted via
    LLMInterrupted at the next check (mid-request or between retries).

    The waiting spinner shows the model the endpoint actually serves (when
    known) and a live elapsed counter, so a long call is visibly alive."""
    disp = endpoints.state(url.rsplit("/chat/completions", 1)[0]).served_model or label
    last = None
    attempt = 0            # 502: the backend is loading, wait long
    transport = 0          # dropped connection: retry fast or fail fast
    while attempt < 5:
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

        who = _who(disp)
        # THE REQUEST FIRST, THE SPINNER AFTER. The two used to be one
        # statement, with the thread started inside the status block - so a
        # spinner that could not be drawn took the call down with it. The
        # request now runs whatever the display does, and a rendering failure
        # is swallowed where it belongs: nobody should lose a memory because
        # a terminal could not draw braille.
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        hook = STATUS_HOOK
        if hook is not None:
            try:
                hook.begin(who)
                while t.is_alive():
                    t.join(timeout=0.5)
                    hook.tick(who, time.time() - start)
            except Exception:
                pass
            finally:
                try:
                    hook.end()
                except Exception:
                    pass
        elif _can_spin():
            try:
                with _console.status(
                    f"[bold cyan]{who} is thinking...[/bold cyan]",
                    spinner="dots",
                ) as status:
                    while t.is_alive():
                        t.join(timeout=0.5)
                        status.update(
                            f"[bold cyan]{who} is thinking... "
                            f"{int(time.time() - start)}s[/bold cyan]")
            except Exception:
                pass
        t.join()
        if holder["exc"] is not None:
            exc = holder["exc"]
            # A dropped connection is not a failed request, it is a request
            # that never arrived — and over an SSH tunnel it is routine: the
            # link blinks, the next attempt half a second later goes through.
            # Until now a single blip cost a whole faculty call, which is how
            # a curator ends up on its deterministic fallback for no reason
            # anyone could name.
            #
            # ConnectionError is exactly the right predicate. ConnectTimeout
            # inherits from it (nothing was established, retry is free);
            # ReadTimeout does NOT (the model has been generating for the whole
            # timeout, and retrying buys another one). LLMInterrupted is a
            # deliberate stop and must never be retried — the interrupt is
            # IMPLEMENTED as a forced ConnectionError, so the order of these
            # checks is what keeps a stop from turning into three more calls.
            if (not isinstance(exc, LLMInterrupted)
                    and isinstance(exc, requests.exceptions.ConnectionError)
                    and transport < 2):
                transport += 1
                wait = 1 if transport == 1 else 3
                _console.print(
                    f"[yellow][llm_client] connection lost — retrying in "
                    f"{wait}s ({transport}/2)[/yellow]")
                time.sleep(wait)
                continue
            raise exc
        last = holder["resp"]
        if last.status_code != 502:
            break
        attempt += 1
        wait = 30 * attempt
        _console.print(
            f"[yellow][llm_client] 502 — waiting {wait}s and retrying "
            f"({attempt}/5)...[/yellow]"
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

# How the most recent call_llm answer was written: thinking, temperature,
# the samplers and seed it sent, and whether a loop forced a retry without
# thinking. Read by the writers of episodes and beliefs right after their call.
LAST_CALL: dict = {}

# Stats of the most recent blocking call: {"prompt","completion","total",
# "seconds","model"}. Read by renderers (batch) to show per-step token counts,
# speed and context usage. Best-effort — empty when the backend sends no usage.
LAST_STATS: dict = {}

# ── Who is calling ────────────────────────────────────────────────────────────
# The spinner used to show the model and nothing else, so every faculty looked
# alike: on a slow endpoint that is minutes of watching a model name with no
# way to tell the curator from the consolidator, or a faculty at work from one
# that is stuck. The same name now also decides where the call goes: see
# endpoints.role_of.
#
# The label is state set around the call rather than an argument threaded
# through call_llm, deliberately. An argument would have to be added at every
# call site, and the site added next year would be the one that forgets it -
# which is precisely the silent-faculty problem again, reappearing as a missing
# parameter. Set here, an unlabelled call falls back to the agent, and any
# faculty added later inherits the behaviour by using the context manager.
#
# Per thread, not per module. Once the name picks an endpoint, a label set on
# one thread must not reach another: the browser interface runs session_reflect
# on a worker thread while the agent works on the request thread, and a shared
# label would send the agent's steps to the memory endpoint for as long as the
# reflection lasted.
_LOCAL = threading.local()


def current_faculty() -> str:
    return getattr(_LOCAL, "faculty", "")


def _current_step() -> str:
    return getattr(_LOCAL, "step", "")


@contextmanager
def faculty(name: str):
    """Name the faculty making the calls inside this block."""
    prev = current_faculty()
    _LOCAL.faculty = name or ""
    try:
        yield
    finally:
        _LOCAL.faculty = prev


@contextmanager
def step(text: str):
    """Progress within one faculty's work, e.g. "2/3" while writing episodes.

    Separate from `faculty` because the two are set by different people: the
    faculty names itself, while only the orchestrator above it knows which of
    how many items is in flight.
    """
    prev = _current_step()
    _LOCAL.step = text or ""
    try:
        yield
    finally:
        _LOCAL.step = prev


def _who(disp: str) -> str:
    """"[CONSOLIDATOR 2/3] model" — or just the model when nothing is set."""
    tag = " ".join(p for p in (current_faculty(), _current_step()) if p)
    return f"[{tag}] {disp}" if tag else disp


_NOTHINK_IGNORED = [False]


def _warn_if_still_thinking(template_kwargs, msg):
    """Say it once when the template ignored a request not to think.

    Asking is not the same as being obeyed, and the difference is invisible:
    the server accepts an unknown chat-template variable without complaint, so
    a template that reads neither key returns a perfectly ordinary reply while
    the model goes on thinking. The banner would say no-think, the wait would
    not change, and nothing anywhere would name the cause.

    Not hypothetical. Two models were probed: one honoured `enable_thinking`
    and `thinking` alike, the other honoured only the first and ignored the
    second in silence. Which key a template reads is a property of the model,
    and the only thing that can notice the mismatch is the reply itself.
    """
    if _NOTHINK_IGNORED[0] or not template_kwargs:
        return
    if not any(v is False for v in template_kwargs.values()):
        return
    if not (msg.get("reasoning_content") or "").strip():
        return
    _NOTHINK_IGNORED[0] = True
    _console.print(
        "[yellow]MEMORY_NO_THINK is set, but the model still returned a "
        "thinking block: this template reads neither key. The memory calls "
        "are as slow as before.[/yellow]")


_THINK_IGNORED = [False]


def _warn_if_not_thinking(template_kwargs, has_reasoning: bool) -> None:
    """Say it once when the model was asked to reason and did not.

    The mirror of _warn_if_still_thinking. A template that does not read the
    key accepts it in silence, so the only witness is the reply: no reasoning
    where reasoning was asked for.
    """
    if _THINK_IGNORED[0] or has_reasoning or not template_kwargs:
        return
    if not any(v is True for v in template_kwargs.values()):
        return
    _THINK_IGNORED[0] = True
    _console.print(
        "[yellow]Pragma asked the model to reason (enable_thinking), but no "
        "reasoning came back: this model or its template may not honour the "
        "switch, or return its reasoning inside the answer.[/yellow]")


def _template_for(base_url, template_kwargs):
    """The template variables to send to this endpoint, or None."""
    if not template_kwargs or endpoints.state(base_url).template_unsupported:
        return None
    return template_kwargs


def _refused(e) -> bool:
    """Did the server refuse the request as written, rather than fail?"""
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status in (400, 422):
        return True
    msg = str(e).lower()
    return any(s in msg for s in ("400", "422", "unknown field", "unsupported",
                                  "unrecognized", "response_format", "json_schema"))


def _post_streamed(url, headers, payload, timeout, label, stop_event):
    """The request as a stream: (message, finish, usage, seconds), or None.

    None means the stream never started - a transport error, a status other
    than 200 or 400/422, a body that is not an event stream, or a connection
    dropped halfway - and the caller makes the blocking request instead, with
    the retries and 502 backoff it has always had. A 400/422 is raised as an
    HTTPError, so a refused field is handled exactly as on the blocking path.

    While it runs, the reasoning goes to the hook as it is written and through
    the loop guard, which raises LLMLooped when a paragraph starts repeating.
    """
    import json as _json
    base = url.rsplit("/chat/completions", 1)[0]
    who = _who(endpoints.state(base).served_model or label)
    body = dict(payload, stream=True, stream_options={"include_usage": True})
    t0 = time.time()
    try:
        resp = requests.post(url, headers=headers, json=body, stream=True, timeout=(10, timeout))
    except requests.RequestException:
        return None
    if resp.status_code in (400, 422):
        text = ""
        try:
            text = resp.text[:300]
        except Exception:
            pass
        resp.close()
        raise requests.HTTPError(f"{resp.status_code} Client Error: {text}", response=resp)
    if resp.status_code != 200 or "text/event-stream" not in (resp.headers.get("Content-Type") or ""):
        resp.close()
        return None

    begin, end, think, say = _hook("begin"), _hook("end"), _hook("reasoning"), _hook("answering")
    status = None
    if begin:
        try:
            begin(who)
        except Exception:
            pass
    elif _can_spin():
        try:
            status = _console.status(f"[bold cyan]{who} is thinking...[/bold cyan]", spinner="dots")
            status.start()
        except Exception:
            status = None
    content, reasoning, finish, usage = "", "", "", {}
    guard = _make_loop_guard()
    # The cap is for the faculties only: the agent may think long on purpose,
    # and its own loop has the step budget and the watchdogs.
    budget = getattr(config, "MEMORY_THINK_BUDGET", 0) if current_faculty() else 0
    try:
        for raw in resp.iter_lines():
            if stop_event is not None and stop_event.is_set():
                raise LLMInterrupted("LLM call aborted by stop signal")
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = _json.loads(data)
            except ValueError:
                continue
            usage = chunk.get("usage") or usage
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("reasoning_content") or ""
            if piece:
                reasoning += piece
                if think:
                    try:
                        think(piece, who)
                    except Exception:
                        pass
                guard.observe(piece, reasoning)
                if budget and not content and len(reasoning) > budget:
                    raise LLMLooped(f"reasoning passed {budget} characters without an answer")
            text = delta.get("content") or ""
            if text:
                content += text
                if say:
                    try:
                        say(text, who)
                    except Exception:
                        pass
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            if status is not None:
                try:
                    status.update(f"[bold cyan]{who} is thinking... {int(time.time() - t0)}s[/bold cyan]")
                except Exception:
                    pass
    except (LLMInterrupted, LLMLooped):
        raise
    except requests.RequestException:
        return None                     # dropped halfway: the blocking request starts over
    finally:
        resp.close()
        if status is not None:
            try:
                status.stop()
            except Exception:
                pass
        if end:
            try:
                end()
            except Exception:
                pass
    return {"content": content, "reasoning_content": reasoning}, finish, usage, time.time() - t0


def _call_openai_compatible(messages, model, temperature, max_tokens, timeout, base_url, api_key, stop_event=None, response_schema=None, template_kwargs=None, sampling=None):
    """Standard OpenAI /chat/completions — works with Groq, Ollama, vLLM, etc."""
    global LAST_STATS
    payload = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  max_tokens,
    }
    # Omitted, not defaulted: an absent field is what hands the choice to
    # the server, exactly as it already does for top_k, top_p and min_p.
    if temperature is not None:
        payload["temperature"] = temperature
    payload.update(config.sampling_extras())
    # The caller's own samplers win over the project's: a memory call that
    # reasons brings the thinking preset and its seed (config.memory_call).
    if sampling:
        payload.update(sampling)
    # Variables handed to the server's chat template: the thinking switch.
    # Not an OpenAI field - a server that rejects it is remembered by the
    # caller and not sent it again.
    if template_kwargs:
        payload["chat_template_kwargs"] = template_kwargs
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
    streamed = None
    if getattr(config, "STREAM_CALLS", True):
        streamed = _post_streamed(f"{base_url}/chat/completions", headers, payload,
                                  timeout, model, stop_event)
    if streamed is not None:
        msg, finish, usage, dt = streamed
    else:
        t0     = time.time()
        resp   = _post_with_retry(f"{base_url}/chat/completions", headers, payload, timeout, model, stop_event)
        dt     = time.time() - t0
        data   = resp.json()
        usage  = data.get("usage") or {}
        choice = data["choices"][0]
        msg    = choice.get("message", {})
        finish = choice.get("finish_reason", "")
    LAST_STATS = {
        "prompt":     usage.get("prompt_tokens", 0) or 0,
        "completion": usage.get("completion_tokens", 0) or 0,
        "total":      usage.get("total_tokens", 0) or 0,
        "seconds":    dt,
        "model":      endpoints.state(base_url).served_model or model,
    }
    _warn_if_still_thinking(template_kwargs, msg)
    _warn_if_not_thinking(template_kwargs, bool((msg.get("reasoning_content") or "").strip()))
    text   = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    return text, finish


# ── Streaming helpers ──────────────────────────────────────────────────────────

def _stream_openai_compatible(messages, model, temperature, max_tokens, timeout,
                               base_url, api_key, stop_event, on_token,
                               on_reasoning=None, template_kwargs=None):
    """Stream from an OpenAI-compatible /chat/completions endpoint (SSE)."""
    import json as _json
    payload = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "stream":      True,
    }
    # Omitted, not defaulted: an absent field is what hands the choice to
    # the server, exactly as it already does for top_k, top_p and min_p.
    if temperature is not None:
        payload["temperature"] = temperature
    payload.update(config.sampling_extras())
    if template_kwargs:
        payload["chat_template_kwargs"] = template_kwargs
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


def _stream_tools_openai_compatible(payload, headers, timeout, base_url,
                                    stop_event, on_token, on_reasoning):
    """The tool channel over SSE: the same dict call_llm_tools returns, or None.

    None means "the stream never started" - a transport error, a status other
    than 200, or a body that is not an event stream - and the caller makes the
    blocking call instead, so every failure keeps the handling it always had.
    Once the stream has started its errors are the call's own.

    Tool calls arrive as fragments keyed by index: the name in one delta, the
    arguments spread over the next fifty. They are joined here and decoded
    once at the end, exactly as the blocking path decodes the whole string.
    Usage comes in the last chunk when the server is asked for it, which is
    what stream_options says; a server that ignores the field simply leaves
    LAST_STATS without token counts, as a blocking reply without usage would.
    """
    import json as _json
    payload = dict(payload, stream=True, stream_options={"include_usage": True})
    try:
        resp = requests.post(f"{base_url}/chat/completions", headers=headers,
                             json=payload, stream=True, timeout=(10, timeout))
    except requests.RequestException:
        return None
    if resp.status_code in (400, 422):
        body = ""
        try:
            body = resp.text[:300]
        except Exception:
            pass
        resp.close()
        raise ToolsUnsupported(f"{resp.status_code} {body}")
    if (resp.status_code != 200
            or "text/event-stream" not in (resp.headers.get("Content-Type") or "")):
        resp.close()
        return None

    content, reasoning, finish, usage = "", "", "", {}
    calls: dict = {}
    guard = _make_loop_guard()
    try:
        for raw in resp.iter_lines():
            if stop_event is not None and stop_event.is_set():
                raise LLMInterrupted("LLM call aborted by stop signal")
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = _json.loads(data)
            except ValueError:
                continue
            usage = chunk.get("usage") or usage
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            thought = delta.get("reasoning_content") or ""
            if thought:
                reasoning += thought
                if on_reasoning:
                    on_reasoning(thought)
                guard.observe(thought, reasoning)
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(int(tc.get("index", 0) or 0),
                                        {"id": "", "name": "", "arguments": ""})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["name"] += fn.get("name") or ""
                arguments = fn.get("arguments")
                if isinstance(arguments, str):
                    slot["arguments"] += arguments
                elif arguments:
                    slot["arguments"] += _json.dumps(arguments)
            text = delta.get("content") or ""
            if text:
                content += text
                if on_token:
                    on_token(text)
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    finally:
        resp.close()

    parsed = []
    for i in sorted(calls):
        slot = calls[i]
        try:
            arguments = (_json.loads(slot["arguments"])
                         if slot["arguments"].strip() else {})
        except ValueError:
            arguments = {"__unparsed_arguments__": slot["arguments"]}
        parsed.append({"id": slot["id"], "name": slot["name"], "arguments": arguments})
    return {"content": content.strip(), "reasoning": reasoning.strip(),
            "tool_calls": parsed, "finish_reason": finish, "usage": usage}


def call_llm_tools(messages, tools, model=None, temperature=None,
                   max_tokens=None, timeout=None, base_url=None, api_key=None,
                   stop_event=None, tool_choice="auto",
                   on_token=None, on_reasoning=None, template_kwargs=None):
    """Ask the model to choose a tool; see _call_llm_tools_once.

    template_kwargs is the thinking switch. A refusal with it attached is
    retried once without, and only a refusal without it means no tools.
    """
    url, _key = _resolved_endpoint(base_url, api_key)
    tk = _template_for(url, template_kwargs)
    args = (messages, tools, model, temperature, max_tokens, timeout,
            base_url, api_key, stop_event, tool_choice, on_token, on_reasoning)
    try:
        result = _call_llm_tools_once(*args, template_kwargs=tk)
    except ToolsUnsupported:
        if not tk:
            raise
        result = _call_llm_tools_once(*args, template_kwargs=None)
        endpoints.state(url).template_unsupported = True
        return result
    has = bool((result.get("reasoning") or "").strip())
    _warn_if_still_thinking(tk, {"reasoning_content": "x" if has else ""})
    _warn_if_not_thinking(tk, has)
    return result


def _call_llm_tools_once(messages, tools, model=None, temperature=None,
                         max_tokens=None, timeout=None, base_url=None, api_key=None,
                         stop_event=None, tool_choice="auto",
                         on_token=None, on_reasoning=None, template_kwargs=None):
    """Ask the model to choose a tool, and read the choice as structured data.

    With on_token or on_reasoning set the reply is streamed and each fragment
    handed over as it arrives; the return value is the same either way.

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

    model       = resolved_model(model)
    temperature = config.DEFAULT_TEMPERATURE if temperature is None else temperature
    max_tokens  = max_tokens or config.MAX_TOKENS
    timeout     = timeout or config.TIMEOUT
    base_url, api_key = _resolved_endpoint(base_url, api_key)

    payload = {
        "model":       model,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "tools":       tools,
        "tool_choice": tool_choice,
    }
    # Omitted, not defaulted: an absent field is what hands the choice to
    # the server, exactly as it already does for top_k, top_p and min_p.
    if temperature is not None:
        payload["temperature"] = temperature
    # Only the samplers actually configured. An absent field is not a missing
    # setting: it hands the choice to the server's launch-time default, which
    # is where a model's recommended preset usually already lives.
    payload.update(config.sampling_extras())
    if template_kwargs:
        payload["chat_template_kwargs"] = template_kwargs
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    global LAST_STATS
    t0 = time.time()
    if on_token is not None or on_reasoning is not None:
        streamed = _stream_tools_openai_compatible(
            payload, headers, timeout, base_url, stop_event, on_token, on_reasoning)
        if streamed is not None:
            usage = streamed.pop("usage", None) or {}
            LAST_STATS = {
                "prompt":     usage.get("prompt_tokens", 0) or 0,
                "completion": usage.get("completion_tokens", 0) or 0,
                "total":      usage.get("total_tokens", 0) or 0,
                "seconds":    time.time() - t0,
                "model":      endpoints.state(base_url).served_model or model,
            }
            return streamed
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
        "model":      endpoints.state(base_url).served_model or model,
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
             base_url=None, api_key=None, stop_event=None, response_schema=None,
             template_kwargs=None, sampling=None):
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
    model = resolved_model(model)
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    url, key = _resolved_endpoint(base_url, api_key)
    known = endpoints.state(url)

    # The schema rides the same switch as the action channel: one flag decides
    # whether this run is constrained end to end or reproduces the old one.
    # MEMORY_SCHEMA=0 additionally ablates the schema while LEAVING the action
    # channel native, which is the only way to attribute a difference in what
    # memory holds to the constraint rather than to the channel.
    #
    # An endpoint that rejected a json_schema once is remembered, so a server
    # without structured output costs one failed request per process instead
    # of one per faculty call - remembered for that endpoint only.
    if (getattr(config, "LLM_TOOL_PROTOCOL", "text") != "native"
            or not getattr(config, "MEMORY_SCHEMA", True)
            or known.schema_unsupported):
        response_schema = None

    # WHAT TO SEND WHEN THE SERVER REFUSES. Two optional fields can make an
    # endpoint reject a request it would otherwise answer: the template
    # variables (an OpenAI server does not know them) and the schema (a server
    # without structured output does not either). Try as asked, then without
    # the template, then without the schema, then without both - and remember
    # what had to go, for this endpoint, so the next call does not pay again.
    # Degrading is better than failing a faculty: the reply is still parsed
    # leniently downstream, exactly as it was before either field existed.
    def _answer(template, temp, samp):
        tk = _template_for(url, template)
        attempts = [(response_schema, tk)]
        if tk:
            attempts.append((response_schema, None))
        if response_schema:
            attempts.append((None, tk))
            if tk:
                attempts.append((None, None))
        last = None
        for schema, templ in attempts:
            try:
                result = _call_openai_compatible(
                    messages, model, temp, max_tokens, timeout, url, key,
                    stop_event, schema, templ, samp,
                )
            except (LLMInterrupted, LLMLooped):
                raise
            except Exception as e:
                if not _refused(e):
                    raise
                last = e
                continue
            if tk and templ is None:
                known.template_unsupported = True
            if response_schema and schema is None:
                known.schema_unsupported = True
                if config.DEBUG:
                    print(f"[llm] endpoint rejected response_format ({str(last)[:120]}); "
                          f"continuing without schemas.")
            return result
        raise last

    # A REASONING THAT GOES IN CIRCLES is stopped by the guard and the same
    # call is asked again without thinking - where a greedy decode has nothing
    # to loop on - so the faculty still gets its answer. Said to the hook (the
    # job log, the conversation) or on the console, never silently: an episode
    # written without the thinking it was meant to have is worth knowing about.
    global LAST_CALL
    LAST_CALL = {}
    asked = bool(template_kwargs) and any(v is True for v in template_kwargs.values())
    looped = False
    try:
        text, finish = _answer(template_kwargs, temperature, sampling)
    except LLMLooped as e:
        # A faculty's call only: the agent's own loop catches this and has
        # its own way back, with a hint to the model rather than a switch.
        if not (asked and current_faculty()):
            raise
        told = _hook("looped")
        who = current_faculty()
        if told:
            try:
                told(who, str(e))
            except Exception:
                pass
        else:
            _console.print(f"[yellow]{who}: the reasoning went in circles - "
                           f"asked again without thinking.[/yellow]")
        # Without thinking there is nothing to loop on, and greedy is safe.
        looped, asked, temperature, sampling = True, False, 0.0, None
        text, finish = _answer({k: False for k in template_kwargs}, temperature, sampling)
    # How this answer was written, for the records that keep it: the episode
    # and the belief say it, so a store written under different regimes can
    # tell its records apart.
    LAST_CALL = {"thinking": asked and not known.template_unsupported,
                 "temperature": temperature, **(sampling or {}), "looped": looped}

    # Salvage partial text on length truncation if possible.
    text = _on_length_finish(text, finish)
    finish = "" if text.startswith(TRUNCATION_PARTIAL_MARKER) else finish
    if not text:
        raise RuntimeError("The model returned an empty response.")

    return text


def stream_llm(messages, model=None, temperature=None, max_tokens=None, timeout=None,
               base_url=None, api_key=None, stop_event=None,
               on_token=None, on_reasoning=None, template_kwargs=None):
    """
    Like call_llm but calls on_token(chunk: str) for each text fragment as it
    arrives over SSE. Returns the complete response text when done.
    """
    model = resolved_model(model)
    if temperature is None: temperature = config.DEFAULT_TEMPERATURE
    if max_tokens  is None: max_tokens  = config.MAX_TOKENS
    if timeout     is None: timeout     = config.TIMEOUT

    url, key = _resolved_endpoint(base_url, api_key)
    tk = _template_for(url, template_kwargs)
    seen = {"reasoning": False}

    def _reasoning(chunk):
        seen["reasoning"] = True
        if on_reasoning:
            on_reasoning(chunk)

    try:
        text = _stream_openai_compatible(
            messages, model, temperature, max_tokens, timeout,
            url, key, stop_event, on_token, _reasoning, tk,
        )
    except requests.HTTPError as e:
        if not (tk and _refused(e)):
            raise
        endpoints.state(url).template_unsupported = True
        return _stream_openai_compatible(
            messages, model, temperature, max_tokens, timeout,
            url, key, stop_event, on_token, on_reasoning, None,
        )
    _warn_if_still_thinking(tk, {"reasoning_content": "x" if seen["reasoning"] else ""})
    _warn_if_not_thinking(tk, seen["reasoning"])
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
