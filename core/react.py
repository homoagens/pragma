# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# react.py — generic ReAct loop (Reasoning + Acting).
#
# An Agent is configured with:
#   - system_prompt : base instructions + description of JSON response formats
#   - skills        : dict {name: callable} — the agent's toolkit
#   - final_keys    : set of JSON keys that, if present in the response,
#                     terminate the loop (e.g. {"conclusion"} or {"final_answer"})
#
# The cycle:
#   1. the LLM responds with JSON containing "thought" + ("action"+"args" or a final_key)
#   2. if a final_key is present → loop done, return the dict
#   3. otherwise execute skills[action](**args), append the OBSERVATION, repeat
#   4. if steps are exhausted → forced verdict
#
# Completely domain-agnostic. What the agent does is determined by
# system_prompt + skills. See README.md for an example.

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.console import Console
from rich.panel import Panel

import config
import llm_client
import memory
from json_parser import extract_json

console = Console()


@dataclass
class AgentConfig:
    """Configuration for a single ReAct agent."""
    name:         str
    system_prompt: str
    skills:       dict                    # {skill_name: callable}
    final_keys:   tuple = ("conclusion",)  # keys that terminate the loop
    model:        Optional[str] = None
    temperature:  Optional[float] = None
    max_steps:    Optional[int] = None
    style:        str = ""                # style description, appended to system_prompt
    # Optional context passed as the first argument to every skill
    # (e.g. case_dir, log_dir, session_id). None = not passed.
    skill_context: object = None
    skill_context_kwarg: str = "context"  # kwarg name used to inject it
    stop_event:    Optional[threading.Event] = None  # set() to interrupt the loop
    on_token:      Optional[Callable] = None  # called with each streamed text chunk
    on_reasoning:  Optional[Callable] = None  # called with each reasoning_content chunk


def _log_step(log_path: Path, entry: dict):
    """Incremental write of each step to a JSON log (list of dicts)."""
    if log_path.exists():
        log = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        log = []
    log.append(entry)
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


# Skills whose payload is a blob of text — the ones whose arguments break the
# JSON layer when the text is source code (newlines, quotes, backslashes).
# Measured over 60 real coding sessions: write_file failed on 41% of .py files
# and 0% of .md ones, and after a failure the model retried the SAME call 57
# times out of 70 — because the error told it to. Where an escape-proof
# variant exists, name it; the retry has to change strategy, not just repeat.
_B64_ALTERNATIVE = {
    "write_file": "write_file_b64",
    "replace_in_file": "replace_in_file_b64",
}
_CONTENT_ARGS = ("content", "new", "old", "instruction")

# Skills that modify a file on disk. Their target is snapshotted before the
# call, so `revert` can undo it. apply_patch is absent on purpose: it can
# touch several files named only inside the diff, and it snapshots its own
# targets before applying.
_MUTATING_SKILLS = {
    "write_file", "write_file_b64", "append_file", "edit_file",
    "replace_in_file", "replace_in_file_b64", "insert_after", "insert_before",
}


def _malformed_args_hint(action: str, kwargs: dict) -> str:
    """Advice for an args-binding failure, aimed at the likely cause.

    A binding failure on a content-carrying skill is almost never the model
    forgetting a parameter: it is the payload having broken the JSON, with
    json-repair then handing back a mangled dict. Repeating the call reproduces
    it exactly, so the hint has to offer a different route.
    """
    carries_content = any(k in kwargs for k in _CONTENT_ARGS)
    alt = _B64_ALTERNATIVE.get(action)

    if carries_content and alt:
        return (
            f"Hint: your `args` JSON was almost certainly malformed by the "
            f"content itself — newlines, quotes and backslashes in source code "
            f"break the JSON layer, and json-repair then loses or invents "
            f"fields. Do NOT retry `{action}` with the same payload: it will "
            f"fail the same way. Use `{alt}` instead, passing the content "
            f"base64-encoded — base64 is pure ASCII, so no escaping can go "
            f"wrong. If the content is long, build the file incrementally: "
            f"`write_file` the scaffolding, then `append_file` one section at "
            f"a time."
        )
    if carries_content:
        return (
            f"Hint: your `args` JSON was probably malformed by the content "
            f"itself — newlines, quotes and backslashes break the JSON layer. "
            f"`{action}` has no base64 variant, so shrink the payload instead: "
            f"send the change in smaller pieces, or write a scaffold first and "
            f"`append_file` the rest one section at a time."
        )
    return (
        "Hint: this often happens when your JSON `args` was malformed and "
        "json-repair dropped fields during recovery. Re-emit the action with "
        "the full args dict, double-checking every required field is present."
    )


def _call_skill(cfg: AgentConfig, action: str, args: dict) -> str:
    """Execute a skill with error handling. Always returns a string.

    Before invoking the skill, validate its signature against the supplied
    args via inspect.signature.bind. This lets us produce a clear,
    actionable error message when the model omits a required arg —
    instead of the cryptic 'missing 1 required positional argument'
    traceback that mentions internal wrapper names."""
    if action not in cfg.skills:
        return f"ERROR: skill '{action}' does not exist. Available: {list(cfg.skills)}"
    fn = cfg.skills[action]
    kwargs = dict(args) if args else {}
    if cfg.skill_context is not None:
        kwargs.setdefault(cfg.skill_context_kwarg, cfg.skill_context)

    # ── Validate signature BEFORE calling ──
    import inspect as _inspect
    try:
        _inspect.signature(fn).bind(**kwargs)
    except TypeError as e:
        # Surface a friendly error that names the missing/unexpected args
        # explicitly. The raw msg ("missing 1 required positional argument:
        # 'path'") is shown after, so the model has both.
        try:
            sig = _inspect.signature(fn)
            required = [p.name for p in sig.parameters.values()
                        if p.default is _inspect.Parameter.empty
                        and p.kind in (_inspect.Parameter.POSITIONAL_ONLY,
                                       _inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                       _inspect.Parameter.KEYWORD_ONLY)
                        and p.name not in (cfg.skill_context_kwarg,)]
            sent_keys = sorted(k for k in kwargs.keys()
                               if k != cfg.skill_context_kwarg)
            missing = [r for r in required if r not in kwargs]
            extra   = [k for k in sent_keys if k not in sig.parameters
                       and not any(p.kind == _inspect.Parameter.VAR_KEYWORD
                                   for p in sig.parameters.values())]
            lines = [
                f"ERROR: invalid arguments for skill `{action}`.",
                f"  you sent     : {sent_keys}",
                f"  required     : {required}",
            ]
            if missing:
                lines.append(f"  MISSING      : {missing}")
            if extra:
                lines.append(f"  unexpected   : {extra}")
            lines.append(f"  raw error    : {e}")
            lines.append(_malformed_args_hint(action, kwargs))
            return "\n".join(lines)
        except Exception:
            return f"ERROR executing {action}: {e}"

    # ── Snapshot before mutating, so the edit can be undone ──
    if action in _MUTATING_SKILLS and kwargs.get("path"):
        try:
            import checkpoint
            checkpoint.snapshot(str(kwargs["path"]))
        except Exception:
            pass          # never let the safety net break the operation

    try:
        return str(fn(**kwargs))
    except Exception as e:
        return f"ERROR executing {action}: {e}"


def run_agent(cfg: AgentConfig, user_task: str, log_path: Optional[Path] = None,
              on_step: Optional[Callable] = None) -> Optional[dict]:
    """
    Start the ReAct loop.
    cfg       : AgentConfig
    user_task : initial user message (what the agent must do)
    log_path  : optional, where to write the narrative step log
    on_step   : optional callback called at each loop event.
                Signature: on_step(event: dict) where event always has "type" and "content".
                Types: "thought" | "action" | "observation" | "final" | "error" | "start"

    Returns the final dict (containing one of the final_keys) or None.
    The dict is enriched with: name, forced (bool).
    """
    def _emit(event: dict):
        if on_step is not None:
            try:
                on_step(event)
            except Exception:
                pass  # the callback must never break the loop

    model       = cfg.model       or config.DEFAULT_MODEL
    temperature = cfg.temperature if cfg.temperature is not None else config.DEFAULT_TEMPERATURE
    max_steps   = cfg.max_steps   or config.MAX_STEPS

    system_prompt = cfg.system_prompt
    if cfg.style:
        system_prompt += f"\n\nOperating style: {cfg.style}"

    if log_path is not None:
        log_path = Path(log_path)
        log_path.write_text("[]", encoding="utf-8")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_task},
    ]

    if config.DEBUG:
        console.print(Panel(
            f"Agent started: [bold]{cfg.name.upper()}[/bold]",
            style="bold red"
        ))
    _emit({"type": "start", "content": cfg.name})

    original_max_steps = max_steps
    step = 1

    # ── Action-loop watchdog state ──
    # Tracks (action_name, args_hash, was_error) for the most recent steps.
    # When N identical entries in a row all return ERROR, we inject a coercive
    # hint to force the model to change strategy (typically: read_file first
    # to see the real state instead of guessing). See config.ACTION_LOOP_*.
    _recent_actions: list[tuple[str, str, bool]] = []

    def _hash_args(a) -> str:
        try:
            import hashlib
            payload = json.dumps(a, sort_keys=True, default=str)
        except Exception:
            payload = str(a)
        return hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()

    while True:
        # ── Stop requested ───────────────────────────────────────────────
        if cfg.stop_event and cfg.stop_event.is_set():
            _emit({"type": "stopped", "content": "Task interrupted by user."})
            return None

        # ── Steps exhausted ───────────────────────────────────────────────
        if step > max_steps:
            ask_fn = cfg.skills.get("ask_user") if cfg.skills else None
            extended = False
            if ask_fn is not None:
                try:
                    answer = ask_fn(
                        "Steps limit reached",
                        f"I have used all {max_steps} available steps. "
                        f"Continue for {original_max_steps} more steps, or conclude with what I have so far?",
                        mode="confirm",
                    )
                    if answer == "yes":
                        max_steps += original_max_steps
                        extended = True
                except Exception:
                    pass
            if extended:
                continue  # re-enter loop at new step (still within new max_steps)
            break         # fall through to forced verdict

        if config.DEBUG:
            console.print(f"\n[dim]━━━ Step {step}/{max_steps} ━━━[/dim]")

        # ── Memory compression ──────────────────────────────────────
        messages = memory.compress(messages, config.MAX_MESSAGES,
                                   f"loop {cfg.name}", model=model)
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars > config.MAX_CHARS:
            if config.DEBUG:
                console.print(
                    f"[yellow]Payload {total_chars} chars — compressing...[/yellow]"
                )
            messages = memory.compress(messages, 0, f"loop {cfg.name}", model=model)

        # ── LLM call ─────────────────────────────────────────────────
        try:
            if cfg.on_token is not None:
                text = llm_client.stream_llm(
                    messages=messages, model=model,
                    temperature=temperature, max_tokens=config.MAX_TOKENS,
                    stop_event=cfg.stop_event, on_token=cfg.on_token,
                    on_reasoning=cfg.on_reasoning,
                )
            else:
                text = llm_client.call_llm(
                    messages=messages, model=model,
                    temperature=temperature, max_tokens=config.MAX_TOKENS,
                    stop_event=cfg.stop_event,
                )
        except llm_client.LLMInterrupted:
            _emit({"type": "stopped", "content": "Task interrupted by user."})
            return None
        except llm_client.LLMLooped as e:
            # Watchdog detected the model is stuck repeating itself inside
            # the <think> block. Abort this turn and inject a recovery hint
            # so the model breaks out of the loop on the next attempt.
            err_str = str(e)
            if config.DEBUG:
                console.print(f"[red]Reasoning loop at step {step}: {err_str}[/red]")
            _emit({"type": "error",
                   "content": f"Reasoning loop detected at step {step}. "
                              f"Aborted to prevent runaway thinking."})
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM]: The watchdog detected that you were REPEATING "
                    "the same paragraph inside your <think> block without "
                    "converging. To recover:\n"
                    "1. STOP analyzing the same code over and over.\n"
                    "2. Either pick the most likely hypothesis and TEST IT "
                    "with a tool call (run, edit, read a specific line), or "
                    "call `ask_user` to request clarification or a runtime "
                    "log from the user (e.g. browser console output).\n"
                    "3. Keep the next `thought` to one sentence.\n"
                    "Reply now with a SINGLE concise JSON action."
                ),
            })
            step += 1
            continue
        except Exception as e:
            err_str = str(e)
            if config.DEBUG:
                console.print(f"[red]LLM error at step {step}: {err_str}[/red]")
            _emit({"type": "error", "content": f"LLM error at step {step}: {err_str}"})

            # If the response was truncated (finish_reason=length), give the
            # model an explicit hint so it changes strategy next turn instead
            # of repeating the same oversized response.
            if "truncated" in err_str.lower() or "finish_reason=length" in err_str.lower():
                messages.append({
                    "role": "user",
                    "content": (
                        "[SYSTEM]: Your previous response was TRUNCATED "
                        "because it exceeded the token limit. To recover:\n"
                        "1. Drastically shorten the `thought` field (one sentence max).\n"
                        "2. Do NOT rewrite entire files. Use `edit_file`, "
                        "`insert_after`, `insert_before`, `append_file`, or "
                        "`replace_in_file` for incremental changes.\n"
                        "3. If the task is large, call `todo_create` ONCE to "
                        "split it into small steps, then execute one step per turn.\n"
                        "Reply now with a SINGLE concise JSON action."
                    ),
                })
            step += 1
            continue

        # ── Detect & strip truncation marker from llm_client ──
        # When finish_reason=length but we got some content, llm_client
        # returns the partial text prefixed with TRUNCATION_PARTIAL_MARKER
        # instead of raising. Strip the marker here and remember it so the
        # JSON parser / fallback can annotate the result appropriately.
        _was_truncated = False
        if text.startswith(llm_client.TRUNCATION_PARTIAL_MARKER):
            _was_truncated = True
            text = text[len(llm_client.TRUNCATION_PARTIAL_MARKER):]
            if config.DEBUG:
                console.print("[yellow]Response truncated — attempting to salvage partial text[/yellow]")

        # ── JSON parsing ─────────────────────────────────────────────
        try:
            response = extract_json(text)
            if _was_truncated and "conclusion" in response:
                # Tag the conclusion so the user sees it was incomplete.
                response["conclusion"] = (
                    "_[NOTE: model response was truncated — partial conclusion below]_\n\n"
                    + str(response["conclusion"])
                )
        except RuntimeError as e:
            # Fallback: if the model responded with plain prose (no JSON at all),
            # treat the full text as a direct conclusion rather than an error.
            # This handles conversational/brainstorming responses from models that
            # ignore the JSON format instruction — AND the case where the
            # response was truncated before the JSON could even start.
            stripped = text.strip()
            if stripped and "{" not in stripped:
                if config.DEBUG:
                    console.print("[yellow]Plain text response — wrapping as conclusion[/yellow]")
                if _was_truncated:
                    response = {"conclusion": (
                        "_[NOTE: model went off-protocol and was then truncated. "
                        "Below is the partial prose response, salvaged.]_\n\n"
                        + stripped
                    )}
                else:
                    response = {"conclusion": stripped}
            elif _was_truncated and stripped:
                # We have SOME text with `{` but parsing failed even after
                # json-repair. Salvage by treating the trailing prose as
                # a conclusion so the user gets something.
                if config.DEBUG:
                    console.print("[yellow]Truncated unparseable JSON — wrapping as conclusion[/yellow]")
                response = {"conclusion": (
                    "_[NOTE: model emitted malformed JSON that was truncated. "
                    "Below is the raw partial output.]_\n\n"
                    + stripped
                )}
            else:
                if config.DEBUG:
                    console.print(f"[red]{e}[/red]")
                _emit({"type": "error", "content": str(e)})
                step += 1
                continue

        # Normalize: the rest of the loop assumes `response` is a dict
        # (action+args / conclusion / etc.). If extract_json returned a
        # list (model emitted `[{...}]` at top level) take the first dict
        # element. If it's neither dict nor list-of-dict, wrap as a
        # conclusion so the user gets the content instead of a crash.
        if isinstance(response, list):
            first = next((x for x in response if isinstance(x, dict)), None)
            response = first if first is not None else {"conclusion": str(response)}
        elif not isinstance(response, dict):
            response = {"conclusion": str(response)}

        # Pull out the json-repair sentinels (if any) and drop them from the
        # response so they don't leak into downstream consumers. Guarded by
        # the normalization above — response is guaranteed dict here.
        _was_repaired = response.pop("__pragma_json_repaired__", False)
        _lost_keys    = response.pop("__pragma_json_lost_keys__", []) or []

        thought = response.get("thought", "")
        if config.DEBUG:
            console.print(Panel(thought, title="THOUGHT", style="bold yellow"))
        _emit({"type": "thought", "content": thought, "step": step})

        # ── FINAL — one of the final_keys is present ──────────────────
        final_key = next((k for k in cfg.final_keys if k in response), None)
        if final_key:
            final_data = {k: response[k] for k in response if k != "thought"}
            if config.DEBUG:
                console.print(Panel(
                    json.dumps(final_data, indent=2, ensure_ascii=False),
                    title="FINAL", style="bold yellow"
                ))
            _emit({"type": "final", "content": response.get(final_key, ""), "data": final_data})
            if log_path is not None:
                _log_step(log_path, {"step": step, **response})
            response["name"]   = cfg.name
            response["forced"] = False
            return response

        # ── ACTION ──────────────────────────────────────────────────
        if "action" not in response:
            # A reply with neither an action nor a final key is almost
            # always a malformed-JSON casualty: json_repair salvaged the
            # `thought` but action/args were dropped (classic cause: single
            # backslashes in Windows paths — invalid JSON escapes). The old
            # behavior skipped WITHOUT appending anything to the messages:
            # at low temperature the model then saw an IDENTICAL context and
            # reproduced the identical broken reply until the step budget
            # ran out, invisible to every watchdog (no action ever executed).
            # Feed the failure back instead, so the context changes and the
            # model can correct itself on the next turn.
            if config.DEBUG:
                console.print("[red]Response has neither action nor final key.[/red]")
            _emit({"type": "error",
                   "content": (f"Step {step}: reply contained neither an "
                               f"`action` nor a final key"
                               + (f" (malformed JSON repaired; dropped keys: "
                                  f"{_lost_keys})" if _was_repaired else "")
                               + ".")})
            feedback = (
                "[SYSTEM]: your previous reply was parsed but contained "
                "neither an `action` nor a final key, so NOTHING was executed"
            )
            if _was_repaired:
                feedback += (
                    ". Your JSON was MALFORMED and had to be repaired; these "
                    f"keys were dropped during recovery: {_lost_keys or '(unknown)'}. "
                    "The most common cause is unescaped backslashes in "
                    "Windows paths: inside JSON strings every backslash must "
                    'be doubled, e.g. "C:\\\\Users\\\\name\\\\file.txt"'
                )
            feedback += (
                ". Re-emit ONE complete JSON object with `thought` plus "
                "either `action`+`args` or a final key. Do not repeat the "
                "previous reply verbatim."
            )
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": feedback})
            step += 1
            continue

        action = response["action"]
        args   = response.get("args", {}) or {}
        if config.DEBUG:
            console.print(f"[cyan]ACTION:[/cyan] {action}({args})")
        _emit({"type": "action", "name": action, "args": args, "step": step})

        observation = _call_skill(cfg, action, args)

        # If json-repair ran AND the skill failed AND the repair dropped
        # known agent-keys, append a diagnostic note. Most failures of this
        # shape are caused exactly by that. Without this hint the model
        # sees a generic "missing arg" and assumes the skill itself is
        # broken (which is what happened in the snake-game session).
        if (_was_repaired and _lost_keys
                and isinstance(observation, str)
                and observation.lstrip().startswith("ERROR")):
            observation = (
                observation
                + "\n\n[JSON-REPAIR NOTE]: your JSON args were malformed "
                "and recovered by the lenient parser. These keys appeared "
                f"in your raw output but did NOT make it into the parsed "
                f"args: {_lost_keys}. Re-emit the action with simpler / "
                "shorter values for these fields (or base64-encode them "
                "via replace_in_file_b64) so the JSON layer doesn't drop "
                "them."
            )
        elif _was_repaired and _lost_keys:
            # Skill succeeded but the repair still lost fields — still warn
            # in case the success was partial / wrong, so the model can
            # double-check the next step.
            observation = (
                observation
                + f"\n\n[JSON-REPAIR NOTE]: parsed via lenient recovery; "
                f"these keys may have been dropped from your args: {_lost_keys}. "
                "Verify the next read_file shows the file in the expected state."
            )

        # Stop may have been raised during the skill (e.g. ask_user, execute_command)
        if cfg.stop_event and cfg.stop_event.is_set():
            _emit({"type": "stopped", "content": "Task interrupted by user."})
            return None

        if config.DEBUG:
            console.print(Panel(observation, title="OBSERVATION", style="cyan"))
        _emit({"type": "observation", "content": observation, "step": step})

        if log_path is not None:
            _log_step(log_path, {
                "step": step, "thought": thought,
                "action": action, "args": args, "observation": observation,
            })

        # Compact very large observations in the conversation history.
        # The full observation is still emitted to the UI (for the user) and
        # logged to disk; only the copy stored for the next LLM turn gets
        # truncated, so the model doesn't carry a 10kB file content forward.
        soft_limit = getattr(config, "OBSERVATION_SOFT_LIMIT", 0)
        if soft_limit > 0 and len(observation) > soft_limit:
            head = observation[: soft_limit // 2]
            tail = observation[-soft_limit // 4 :]
            stored_obs = (
                f"{head}\n"
                f"\n[... observation truncated — full length {len(observation)} chars. "
                f"Use read_file with start_line/end_line or grep_search for targeted access ...]\n"
                f"\n{tail}"
            )
        else:
            stored_obs = observation

        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role":    "user",
            "content": f"[OBSERVATION]: {stored_obs}",
        })

        # ── Action-loop watchdog ──
        # Record this (action, args, was_error) triple and check if the
        # model is hammering the same failing call. If yes, append a coercive
        # recovery hint to nudge it toward a different strategy.
        if getattr(config, "ACTION_LOOP_ENABLED", True):
            is_error = isinstance(observation, str) and observation.lstrip().startswith("ERROR")
            _recent_actions.append((action, _hash_args(args), is_error))
            if len(_recent_actions) > 10:
                _recent_actions[:] = _recent_actions[-10:]
            threshold = getattr(config, "ACTION_LOOP_THRESHOLD", 3)
            tail = _recent_actions[-threshold:]
            if (len(tail) == threshold
                    and all(t[0] == action and t[1] == tail[0][1] and t[2]
                            for t in tail)):
                _emit({
                    "type": "error",
                    "content": (
                        f"Action loop detected at step {step}: "
                        f"`{action}` called {threshold}× in a row with identical "
                        f"arguments, every call returned ERROR."
                    ),
                })
                messages.append({
                    "role": "user",
                    "content": (
                        f"[SYSTEM]: ACTION LOOP DETECTED. You have called "
                        f"`{action}` with IDENTICAL arguments {threshold} times "
                        f"in a row and every call returned ERROR. Your mental "
                        f"model of the file/system state has diverged from "
                        f"reality. STOP repeating this call.\n\n"
                        f"Mandatory recovery — pick whichever fits the situation:\n"
                        f"a) If the error is 'substring not found' or you don't "
                        f"know the file's actual current state: call `read_file` "
                        f"(or `file_outline` for large files) FIRST, then base "
                        f"your next action on what you READ — not on what you "
                        f"remember writing.\n"
                        f"b) If you've already tried multiple different "
                        f"approaches and none have worked, call `ask_user` "
                        f"with a brief summary of what you tried, what failed, "
                        f"and a SPECIFIC question or set of options for the "
                        f"user. Asking does NOT count as failure — it's the "
                        f"correct move when you're stuck.\n"
                        f"c) If the user's request can be interpreted multiple "
                        f"ways and you've been guessing wrong, call `ask_user` "
                        f"to disambiguate.\n"
                        f"d) Do NOT call `{action}` with the same arguments again."
                    ),
                })
                # Reset so we don't fire on EVERY subsequent step indefinitely.
                _recent_actions.clear()

        # ── Error-rate watchdog ──
        # Complements the strict (action,args) loop above. Detects the
        # "thrashing across different skills, all erroring" pattern where
        # the model tries 5 different things and none work. The strict
        # watchdog misses this case by design.
        if getattr(config, "ACTION_LOOP_ENABLED", True) and _recent_actions:
            window = getattr(config, "ERROR_RATE_WINDOW", 5)
            thresh = getattr(config, "ERROR_RATE_THRESHOLD", 0.75)
            recent = _recent_actions[-window:]
            if len(recent) >= window:
                err_n = sum(1 for t in recent if t[2])
                if err_n / window >= thresh:
                    _emit({
                        "type": "error",
                        "content": (
                            f"High error rate at step {step}: "
                            f"{err_n}/{window} of recent actions returned ERROR."
                        ),
                    })
                    messages.append({
                        "role": "user",
                        "content": (
                            f"[SYSTEM]: HIGH ERROR RATE — {err_n} of your last "
                            f"{window} tool calls returned ERROR, even though "
                            f"you tried different skills. You are not progressing.\n\n"
                            "Stop and reset. Mandatory next move — pick ONE:\n"
                            "  a) Call `ask_user` with a clear summary of what "
                            "you tried, what failed, and a SPECIFIC question or "
                            "list of options. The user can unblock you.\n"
                            "  b) Call `read_file` / `file_outline` / `list_dir` "
                            "to ground yourself in the actual current state, "
                            "then start fresh with one small action.\n"
                            "  c) If the task is too ambiguous to proceed, "
                            "produce a `conclusion` explaining what you tried, "
                            "why it failed, and what info you'd need to retry.\n\n"
                            "Do NOT try a 6th different skill blindly."
                        ),
                    })
                    # Clear so we don't re-fire every step
                    _recent_actions.clear()

        step += 1  # advance step counter for the while loop

    # ── Steps exhausted — forced verdict ─────────────────────────────
    if config.DEBUG:
        console.print("[yellow]Steps exhausted — requesting forced verdict...[/yellow]")
    final_list = " or ".join(f'"{k}"' for k in cfg.final_keys)
    messages.append({
        "role": "user",
        "content": (
            f"You have exhausted your available steps. "
            f"Using the information gathered so far, produce NOW a final response "
            f"in JSON format with one of these keys: {final_list}. "
            f"You must conclude — you cannot request further actions."
        )
    })
    messages = memory.compress(messages, config.MAX_MESSAGES,
                               f"forced {cfg.name}", model=model)

    try:
        if cfg.on_token is not None:
            text = llm_client.stream_llm(
                messages=messages, model=model,
                temperature=temperature, max_tokens=config.MAX_TOKENS,
                stop_event=cfg.stop_event, on_token=cfg.on_token,
                on_reasoning=cfg.on_reasoning,
            )
        else:
            text = llm_client.call_llm(
                messages=messages, model=model,
                temperature=temperature, max_tokens=config.MAX_TOKENS,
                stop_event=cfg.stop_event,
            )
        response = extract_json(text)
    except llm_client.LLMInterrupted:
        _emit({"type": "stopped", "content": "Task interrupted by user."})
        return None
    except Exception as e:
        if config.DEBUG:
            console.print(f"[red]Forced verdict failed: {e}[/red]")
        return None

    thought = response.get("thought", "")
    if config.DEBUG:
        console.print(Panel(thought, title="THOUGHT (forced)", style="bold yellow"))
        console.print(Panel(
            json.dumps(
                {k: response[k] for k in response if k != "thought"},
                indent=2, ensure_ascii=False,
            ),
            title="FINAL (forced)", style="bold yellow"
        ))
    if log_path is not None:
        _log_step(log_path, {"step": max_steps + 1, **response, "forced": True})
    response["name"]   = cfg.name
    response["forced"] = True
    return response
