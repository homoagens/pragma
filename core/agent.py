# agent.py — generic ReAct loop (Reasoning + Acting).
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


def _call_skill(cfg: AgentConfig, action: str, args: dict) -> str:
    """Execute a skill with error handling. Always returns a string."""
    if action not in cfg.skills:
        return f"ERROR: skill '{action}' does not exist. Available: {list(cfg.skills)}"
    try:
        fn = cfg.skills[action]
        kwargs = dict(args)
        if cfg.skill_context is not None:
            kwargs.setdefault(cfg.skill_context_kwarg, cfg.skill_context)
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

        # ── JSON parsing ─────────────────────────────────────────────
        try:
            response = extract_json(text)
        except RuntimeError as e:
            # Fallback: if the model responded with plain prose (no JSON at all),
            # treat the full text as a direct conclusion rather than an error.
            # This handles conversational/brainstorming responses from models that
            # ignore the JSON format instruction.
            stripped = text.strip()
            if stripped and "{" not in stripped:
                if config.DEBUG:
                    console.print("[yellow]Plain text response — wrapping as conclusion[/yellow]")
                response = {"conclusion": stripped}
            else:
                if config.DEBUG:
                    console.print(f"[red]{e}[/red]")
                _emit({"type": "error", "content": str(e)})
                step += 1
                continue

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
            if config.DEBUG:
                console.print("[red]Response has neither action nor final key — skipping.[/red]")
            step += 1
            continue

        action = response["action"]
        args   = response.get("args", {}) or {}
        if config.DEBUG:
            console.print(f"[cyan]ACTION:[/cyan] {action}({args})")
        _emit({"type": "action", "name": action, "args": args, "step": step})

        observation = _call_skill(cfg, action, args)

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
