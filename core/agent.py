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
from dataclasses import dataclass, field
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

    while True:
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
            text = llm_client.call_llm(
                messages=messages, model=model,
                temperature=temperature, max_tokens=config.MAX_TOKENS,
            )
        except Exception as e:
            if config.DEBUG:
                console.print(f"[red]LLM error at step {step}: {e}[/red]")
            _emit({"type": "error", "content": f"LLM error at step {step}: {e}"})
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
        if config.DEBUG:
            console.print(Panel(observation, title="OBSERVATION", style="cyan"))
        _emit({"type": "observation", "content": observation, "step": step})

        if log_path is not None:
            _log_step(log_path, {
                "step": step, "thought": thought,
                "action": action, "args": args, "observation": observation,
            })

        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user",      "content": f"[OBSERVATION]: {observation}"})

        step += 1  # advance step counter for the while loop

    # ── Steps exhausted — forced verdict ─────────────────────────────
    if config.DEBUG:
        console.print(f"[yellow]Steps exhausted — requesting forced verdict...[/yellow]")
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
        text = llm_client.call_llm(
            messages=messages, model=model,
            temperature=temperature, max_tokens=config.MAX_TOKENS,
        )
        response = extract_json(text)
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
