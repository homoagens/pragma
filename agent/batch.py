# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# agent/batch.py — headless batch entry point for Pragma
#
# Runs ONE task start-to-finish, no UI, no interaction. Every reasoning
# step (thought / action / observation) streams to stdout so the whole
# run can be watched live or redirected to a log file:
#
#   python -m agent.batch --task "fix the failing test" --cwd C:\proj
#   python -m agent.batch --task-file task.txt --cwd /proj > run.md
#   echo "list all TODOs in this repo" | python -m agent.batch --cwd /proj
#
# Output modes (auto-detected, overridable):
#   pretty   — default when stdout is a terminal. Rendered live via rich:
#              colored step rules, dim thoughts, cyan actions, guttered
#              observations, and the conclusion as real Markdown in a panel.
#   markdown — default when stdout is redirected (`> run.md`). A clean
#              Markdown document with timestamps in the step headings.
#              View it rendered with: glow run.md
#              (or: python -m rich.markdown run.md)
#   plain    — the flat `[HH:MM:SS] STEP n ...` format, stable for grepping
#              from scripts. Force with --plain.
#   --md forces raw markdown even on a terminal; --plain forces flat text.
#
# Streams:
#   stdout — run banner, step events, final conclusion
#   stderr — fatal errors only (bad arguments, unreachable LLM endpoint)
#
# Exit codes:
#   0  clean conclusion
#   2  forced verdict (step budget exhausted, the agent was told to wrap up)
#   1  failure (no result, endpoint unreachable, bad input)
#
# Deliberate differences from the web UI:
#   - ask_user never blocks: confirm questions get "no" (fail-safe for
#     destructive confirmations), open questions get a canned "no user
#     available" answer telling the model to proceed or conclude.
#   - Stateless by default: no thread persistence, no conversation history.
#   - Memory is opt-in with --memory: at start it injects relevant episodes
#     (recall_episodes) and learnings (recall_learnings); at the end it
#     consolidates the session into an episode (episode_consolidate), which
#     may also distill semantic assertions when patterns recur.
#   - A PRAGMA.md file in the workspace root (user-authored instructions,
#     e.g. standing authorizations) is ALWAYS injected when present — it is
#     the project contract, not memory, so it doesn't need --memory.
#   - Temperature defaults to 0.0 for reproducible runs (the UI uses 0.2).

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ── path setup (same as server.py) ───────────────────────────────────────────
_HERE = Path(__file__).resolve().parent   # Pragma/agent/
_ROOT = _HERE.parent                       # Pragma/
_CORE = _ROOT / "core"

for _p in (str(_CORE), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as baseline_config
import llm_client
from react import AgentConfig, run_agent
from skills import ALL_SKILLS, SKILLS_SUMMARY
from agent.prompts import build_system_prompt


# ── output helpers ────────────────────────────────────────────────────────────
# Everything goes through _out/_err so the flush policy lives in one place:
# without flush=True a redirect (`> run.md`) would buffer the whole run and
# show nothing until exit — and lose everything if the process is killed.

def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _out(line: str = "") -> None:
    print(line, flush=True)


def _err(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _fmt_args_json(args) -> str:
    """Raw-JSON args rendering used by plain mode (grep-stable)."""
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        s = str(args)
    if len(s) > 400:
        s = s[:400] + f" ...[+{len(s) - 400} chars]"
    return s


def _fmt_args_kv(args: dict, max_val: int = 120) -> str:
    """Human-friendly `key="value"` args rendering used by pretty/markdown
    modes: no JSON braces, no doubled backslashes, newlines made visible,
    long values clipped per-key."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if isinstance(v, str):
            s = v.replace("\n", "\\n")
            if len(s) > max_val:
                s = s[:max_val] + "..."
            parts.append(f'{k}="{s}"')
        else:
            try:
                s = json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                s = str(v)
            if len(s) > max_val:
                s = s[:max_val] + "..."
            parts.append(f"{k}={s}")
    return ", ".join(parts)


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """Return (possibly clipped text, was_clipped)."""
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit], True


# ── renderers ─────────────────────────────────────────────────────────────────
# One renderer per output mode, same duck-typed interface. main() picks one
# and stores it in _RENDERER so batch_ask_user can reach it too.

class _PlainRenderer:
    """The original flat format: `[HH:MM:SS] STEP n  KIND  content`.
    Kept byte-compatible with the first batch.py so scripts that grep
    these logs don't break. Selected with --plain."""

    @staticmethod
    def _tag(step) -> str:
        return f"STEP {step:>2}" if step else "       "

    def banner(self, cwd, model_line, endpoint, max_steps, task):
        head = task.splitlines()[0]
        if len(head) > 120:
            head = head[:120] + "..."
        _out(f"[{_ts()}] PRAGMA BATCH")
        _out(f"[{_ts()}] cwd        : {cwd}")
        _out(f"[{_ts()}] model      : {model_line}")
        _out(f"[{_ts()}] endpoint   : OK ({endpoint})")
        _out(f"[{_ts()}] max steps  : {max_steps}")
        _out(f"[{_ts()}] task       : {head}")
        _out()

    def thought(self, step, text):
        _out(f"[{_ts()}] {self._tag(step)}  THOUGHT      {text}")

    def action(self, step, name, args):
        _out(f"[{_ts()}] {self._tag(step)}  ACTION       {name} {_fmt_args_json(args)}")

    def observation(self, step, content, limit):
        _out(f"[{_ts()}] {self._tag(step)}  OBSERVATION  ({len(content)} chars)")
        shown, clipped = _clip(content, limit)
        _out(shown)
        if clipped:
            _out(f"... [truncated for display - {len(content)} chars total; "
                 f"full text in the --log file]")
        _out()

    def ask(self, question, context):
        line = f"[{_ts()}]          ASK_USER     {question}"
        if context:
            line += f"  (context: {context})"
        _out(line)

    def ask_answer(self, text):
        _out(f"[{_ts()}]          ASK_USER     -> {text}")

    def final(self, step, content):
        _out(f"[{_ts()}]          FINAL        conclusion below")

    def error(self, step, content):
        _out(f"[{_ts()}] {self._tag(step)}  ERROR        {content}")

    def conclusion(self, forced, elapsed, text):
        label = "FORCED (step budget exhausted)" if forced else "CLEAN"
        _out()
        _out(f"[{_ts()}] ===== CONCLUSION - {label} - {elapsed:.0f}s =====")
        _out(text)

    def memory_running(self):
        _out()
        _out(f"[{_ts()}] MEMORY       consolidating episode...")

    def memory_done(self, summary):
        _out(f"[{_ts()}] MEMORY       {summary}")


class _MarkdownRenderer:
    """Raw Markdown document — the default when stdout is redirected.
    Timestamps live in the step headings. The thought is buffered for one
    event so the heading can carry the action name (`### Step 2 ·
    `execute_command` · 23:14:07`); it is flushed as a blockquote under it."""

    def __init__(self):
        self._pending: tuple | None = None   # (step, thought_text, ts)

    def _flush(self, action_name: str = "", args_line: str = ""):
        if self._pending is None and not action_name:
            return
        step, text, ts = self._pending or (None, "", _ts())
        head = f"### Step {step}" if step else "### Step"
        if action_name:
            head += f" · `{action_name}`"
        head += f" · {ts}"
        _out(head)
        _out()
        if text:
            _out(f"> {text}")
            _out()
        if args_line:
            _out(f"**args**: `{args_line}`")
            _out()
        self._pending = None

    def banner(self, cwd, model_line, endpoint, max_steps, task):
        head = task.splitlines()[0]
        if len(head) > 120:
            head = head[:120] + "..."
        _out(f"# Pragma batch — {head}")
        _out()
        _out(f"- **cwd**: {cwd}")
        _out(f"- **model**: {model_line}")
        _out(f"- **endpoint**: OK ({endpoint})")
        _out(f"- **max steps**: {max_steps}")
        _out()

    def thought(self, step, text):
        self._flush()  # a previous thought never got its action — emit it bare
        self._pending = (step, text, _ts())

    def action(self, step, name, args):
        args_line = _fmt_args_kv(args).replace("`", "'")
        self._flush(action_name=name, args_line=args_line)

    def observation(self, step, content, limit):
        self._flush()
        shown, clipped = _clip(content, limit)
        # A longer fence keeps the block intact if the content itself
        # contains ``` (e.g. a read_file of a markdown document).
        fence = "````" if "```" in shown else "```"
        _out(f"{fence}text")
        _out(shown)
        _out(fence)
        if clipped:
            _out(f"_[truncated for display — {len(content)} chars total; "
                 f"full text in the --log file]_")
        _out()

    def ask(self, question, context):
        self._flush()
        _out(f"**ask_user**: {question}")
        if context:
            _out(f"— _{context}_")

    def ask_answer(self, text):
        _out(f"**answer**: {text}")
        _out()

    def final(self, step, content):
        self._flush()  # emit the closing thought before the conclusion

    def error(self, step, content):
        self._flush()
        _out(f"**ERROR**: {content}")
        _out()

    def conclusion(self, forced, elapsed, text):
        self._flush()
        label = "forced (step budget exhausted)" if forced else "clean"
        _out("---")
        _out()
        _out(f"## Conclusion — {label}, {elapsed:.0f}s")
        _out()
        _out(text)

    def memory_running(self):
        _out()
        _out("**memory**: consolidating episode...")

    def memory_done(self, summary):
        _out(f"**memory**: {summary}")


class _PrettyRenderer:
    """Live terminal rendering via rich — the default when stdout is a TTY.
    No timestamps (they're noise live); hierarchy is typographic: dim italic
    thoughts, cyan action names, grey guttered observations, and the
    conclusion rendered as real Markdown inside a panel."""

    def __init__(self):
        from rich.console import Console
        self.console = Console(highlight=False)
        self._last_step = None
        # Legacy conhost (pre-Windows Terminal) can't print ▶ or │ — rich
        # substitutes its OWN drawing chars (rules, panel borders) there,
        # but characters we embed in Text are our problem. Fall back to
        # ASCII on legacy consoles, keep the nicer glyphs elsewhere.
        legacy = getattr(self.console, "legacy_windows", False)
        self._arrow  = "  > " if legacy else "  ▶ "
        self._gutter = "  | " if legacy else "  │ "

    def _rule(self, step):
        if step is not None and step != self._last_step:
            self._last_step = step
            self.console.print()
            self.console.rule(f"[bold]Step {step}[/bold]",
                              align="left", style="bright_black")

    def banner(self, cwd, model_line, endpoint, max_steps, task):
        from rich.text import Text
        head = task.splitlines()[0]
        if len(head) > 100:
            head = head[:100] + "..."
        t = Text(" Pragma", style="bold")
        t.append(f" · {model_line} · {cwd} · max {max_steps} steps",
                 style="bright_black")
        self.console.print(t)
        self.console.print(Text(f" task: {head}", style="bright_black"))

    def thought(self, step, text):
        from rich.text import Text
        self._rule(step)
        self.console.print(Text("  " + text, style="italic bright_black"))

    def action(self, step, name, args):
        from rich.text import Text
        self._rule(step)
        t = Text(self._arrow)
        t.append(name, style="bold cyan")
        t.append(f"({_fmt_args_kv(args)})", style="bright_black")
        self.console.print(t)

    def observation(self, step, content, limit):
        from rich.text import Text
        self._rule(step)
        shown, clipped = _clip(content, limit)
        for line in shown.splitlines() or [""]:
            self.console.print(Text(self._gutter + line, style="bright_black"))
        if clipped:
            self.console.print(Text(
                f"{self._gutter}... truncated for display - {len(content)} "
                f"chars total (full text in the --log file)",
                style="italic yellow"))

    def ask(self, question, context):
        from rich.text import Text
        t = Text("  ? ask_user — ", style="bold yellow")
        t.append(question, style="yellow")
        self.console.print(t)
        if context:
            self.console.print(Text("    " + context, style="bright_black"))

    def ask_answer(self, text):
        from rich.text import Text
        self.console.print(Text("  -> " + text, style="yellow"))

    def final(self, step, content):
        pass  # the conclusion panel follows immediately

    def error(self, step, content):
        from rich.text import Text
        self._rule(step)
        t = Text("  ERROR — ", style="bold red")
        t.append(content, style="red")
        self.console.print(t)

    def conclusion(self, forced, elapsed, text):
        from rich.markdown import Markdown
        from rich.panel import Panel
        label = "forced (step budget exhausted)" if forced else "clean"
        border = "yellow" if forced else "green"
        self.console.print()
        self.console.print(Panel(Markdown(text),
                                 title=f"Conclusion — {label}, {elapsed:.0f}s",
                                 title_align="left", border_style=border))

    def memory_running(self):
        from rich.text import Text
        self.console.print(Text("  memory: consolidating episode...",
                                style="bright_black"))

    def memory_done(self, summary):
        from rich.text import Text
        self.console.print(Text("  memory: " + summary,
                                style="bright_black"))


_RENDERER = None  # set by main(); used by batch_ask_user


# ── batch replacement for ask_user ────────────────────────────────────────────
# Same pattern the server uses with ws_ask_user: swap the skill in the dict.
# In batch there is no human, so this must never block. It also answers the
# forced-verdict "continue for more steps?" confirm in react.py with "no",
# which is exactly the batch behavior we want (conclude, don't extend).

def batch_ask_user(topic: str = "", context: str = "", mode: str = "input",
                   prompt: str = "", question: str = "", **_ignored) -> str:
    """Non-blocking ask_user for batch runs. Logs the question, returns a
    canned answer: 'no' for confirm mode (destructive confirmations fail
    safe), a 'no user available' notice otherwise."""
    q = topic or prompt or question
    r = _RENDERER
    if r:
        r.ask(q, context)
    if mode == "confirm":
        if r:
            r.ask_answer("'no' (batch mode, fail-safe)")
        return "no"
    answer = ("(batch mode - no user is available and NO confirmation can be "
              "given. This reply is NOT a confirmation and NOT an "
              "authorization. If you were asking permission for a destructive "
              "or irreversible action (delete, overwrite, force-push, drop, "
              "mass-edit), treat the answer as NO unless the action is "
              "already explicitly authorized in the task text or in the "
              "project instructions — in that case rely on THAT "
              "authorization, not on this reply. If you were asking a "
              "non-destructive clarification, proceed with your best "
              "judgment, or conclude explaining exactly what information "
              "is missing.)")
    if r:
        r.ask_answer("canned batch answer")
    return answer


# ── step router ───────────────────────────────────────────────────────────────

def _make_on_step(renderer, obs_limit: int, transcript: list[str]):
    """Build the on_step callback for run_agent. Routes each event to the
    active renderer and appends a compact line to `transcript` (same shape
    the server feeds to the consolidation worker, used here only with
    --memory)."""

    def on_step(ev: dict) -> None:
        t = ev.get("type", "")
        step = ev.get("step")

        if t == "thought":
            text = " ".join(str(ev.get("content", "")).split())
            renderer.thought(step, text)
            transcript.append(f"THOUGHT: {text[:300]}")
        elif t == "action":
            name = ev.get("name", "")
            args = ev.get("args", {}) or {}
            renderer.action(step, name, args)
            transcript.append(f"ACTION: {name}({_fmt_args_kv(args)})"[:300])
        elif t == "observation":
            content = str(ev.get("content", ""))
            renderer.observation(step, content, obs_limit)
            transcript.append(f"OBS: {content[:300]}")
        elif t == "final":
            renderer.final(step, str(ev.get("content", "")))
            transcript.append(f"FINAL: {str(ev.get('content', ''))[:300]}")
        elif t == "error":
            content = str(ev.get("content", ""))
            renderer.error(step, content)
            transcript.append(f"ERROR: {content[:300]}")
        # "start" and unknown types: noise, skip.

    return on_step


# ── main ──────────────────────────────────────────────────────────────────────

def _read_task(args, parser: argparse.ArgumentParser) -> str:
    if args.task:
        return args.task
    if args.task_file:
        p = Path(args.task_file)
        if not p.is_file():
            parser.error(f"task file not found: {p}")
        return p.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    parser.error("no task: pass --task, --task-file, or pipe the task on stdin")
    return ""  # unreachable — parser.error raises SystemExit


def main() -> int:
    global _RENDERER

    parser = argparse.ArgumentParser(
        prog="python -m agent.batch",
        description="Pragma — headless batch runner (one task, no UI, "
                    "no interaction). Steps stream to stdout: rendered "
                    "live on a terminal, raw markdown when redirected.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--task", help="task text")
    src.add_argument("--task-file", help="read the task from this file")
    parser.add_argument("--cwd", default=None,
                        help="working directory for the task (default: current)")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="step budget (default: MAX_STEPS from .env, "
                             f"currently {baseline_config.MAX_STEPS})")
    parser.add_argument("--log", default=None,
                        help="write the full structured step log (JSON) here")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="sampling temperature (default 0.0 for "
                             "reproducible runs)")
    parser.add_argument("--obs-limit", type=int, default=600,
                        help="max chars of each observation printed to stdout "
                             "(0 = unlimited; the --log file always gets the "
                             "full text)")
    parser.add_argument("--memory", action="store_true",
                        help="enable memory: inject relevant episodes and "
                             "learnings at start, consolidate this session "
                             "into an episode at the end")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--plain", action="store_true",
                     help="force the flat [HH:MM:SS] format (grep-stable)")
    fmt.add_argument("--md", action="store_true",
                     help="force raw markdown output even on a terminal")
    args = parser.parse_args()

    # UTF-8-safe printing even when stdout/stderr are redirected on Windows
    # (redirected streams default to the locale codepage, e.g. cp1252, and a
    # unicode char in an observation would crash the printer mid-run).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Output mode: explicit flag wins; otherwise TTY → pretty, pipe → markdown.
    if args.plain:
        _RENDERER = _PlainRenderer()
    elif args.md or not sys.stdout.isatty():
        _RENDERER = _MarkdownRenderer()
    else:
        _RENDERER = _PrettyRenderer()
    renderer = _RENDERER

    task = _read_task(args, parser).strip()
    if not task:
        _err("ERROR: task is empty.")
        return 1

    # cwd: batch is one process = one task, so a plain chdir is safe (no
    # concurrency across threads like in server.py). Relative paths in the
    # filesystem skills then resolve against the project, and the system
    # prompt instructs the model to build absolute paths from this cwd.
    cwd = Path(args.cwd or os.getcwd()).resolve()
    if not cwd.is_dir():
        _err(f"ERROR: not a directory: {cwd}")
        return 1
    os.chdir(cwd)

    # Fail fast if the LLM endpoint is down — in batch there is no Settings
    # panel to fix it from, and run_agent would just error on every step.
    ok, detail = llm_client.ping_models()
    if not ok:
        _err(f"ERROR: LLM endpoint unreachable — {detail}")
        _err("Run configure (or edit .env) and retry.")
        return 1

    coding_model = baseline_config.CODING_MODEL or baseline_config.DEFAULT_MODEL
    model_line = baseline_config.DEFAULT_MODEL
    if coding_model != baseline_config.DEFAULT_MODEL:
        model_line += f"  (code skill -> {coding_model})"
    max_steps = args.max_steps or baseline_config.MAX_STEPS

    renderer.banner(str(cwd), model_line, detail, max_steps, task)

    skills = dict(ALL_SKILLS)
    skills["ask_user"] = batch_ask_user

    # Batch-only system prompt addendum. The generic "confirm destructive
    # ops with the user" rule is useless here (there IS no user), and models
    # stretch vague requests ("clean up") into implicit authorization. Give
    # them a DECIDABLE rule instead: explicit operation + explicit target,
    # or no destruction.
    batch_policy = """

## Batch mode — destructive operations policy

This session is NON-INTERACTIVE: no user is available, nothing can be
confirmed mid-task. Therefore:

- An operation is DESTRUCTIVE if it deletes, overwrites or irreversibly
  alters existing files or data: del / rm / rmdir / rd, overwrite=true on
  an existing file, mass edits, git reset/clean, DROP/TRUNCATE, and similar.
- You may perform a destructive operation ONLY IF the task text names the
  operation AND its specific target (e.g. "delete ricette.md", "overwrite
  config.json"), or the project instructions above pre-authorize exactly
  that kind of operation on this workspace.
- Vague requests ("clean up", "make some space", "tidy this folder",
  "reorganize") are NOT authorization to destroy anything. Do the
  non-destructive part, then LIST in the conclusion exactly what you would
  remove and tell the user to re-run with an explicit instruction.
- Do NOT call ask_user to obtain this authorization: nobody can answer.
  Decide by the rule above — and when in doubt, don't destroy.
- Prior sessions in your memory where destructive actions succeeded are
  NOT precedents that authorize new ones: authorization never comes from
  memory, only from the current task text or the project instructions.
"""
    system_prompt = build_system_prompt(
        str(cwd),
        default_model=baseline_config.DEFAULT_MODEL,
        coding_model=coding_model,
        skills_summary=SKILLS_SUMMARY,
    ) + batch_policy

    # ── Task assembly: instructions + memory + current request ──────────
    # PRAGMA.md is the user-authored project contract (standing rules,
    # authorizations): injected whenever present, no flag needed. The
    # memory blocks (episodes + learnings) are opt-in with --memory and
    # explicitly marked as possibly-outdated context, not instructions.
    prefix_parts: list[str] = []

    pragma_md = cwd / "PRAGMA.md"
    if pragma_md.is_file():
        try:
            instructions = pragma_md.read_text(encoding="utf-8").strip()
        except Exception:
            instructions = ""
        if instructions:
            cap = getattr(baseline_config, "PRAGMA_MD_MAX_CHARS", 4000)
            if len(instructions) > cap:
                instructions = instructions[:cap] + "\n[... truncated]"
            prefix_parts.append(
                "[Project instructions — authored by the user for this "
                "workspace, follow them. The PRAGMA.md file they come from "
                "is READ-ONLY for you: never create, modify or delete it]\n"
                + instructions)

    if args.memory:
        try:
            from skills.recall_episodes.skill import recall_episodes
            block = recall_episodes(query=task, workspace=str(cwd))
            if block and not block.startswith("(no episodes"):
                prefix_parts.append(
                    "[Episodic memory — condensed notes from previous "
                    "sessions; may be outdated, verify against the actual "
                    "files]\n" + block)
        except Exception:
            pass
        try:
            from skills.recall_learnings.skill import recall_learnings
            block = recall_learnings(query=task)
            if (block and not block.startswith("(no learnings")
                    and not block.startswith("ERROR")):
                prefix_parts.append(
                    "[Relevant prior learnings — short heuristics from past "
                    "tasks, use only if they fit the current request]\n" + block)
        except Exception:
            pass

    full_task = task
    if prefix_parts:
        full_task = ("\n\n".join(prefix_parts)
                     + "\n\n[Current request]\n" + task)

    transcript: list[str] = [f"USER: {task}"]
    cfg = AgentConfig(
        name="Pragma",
        system_prompt=system_prompt,
        skills=skills,
        final_keys=("conclusion",),
        model=baseline_config.DEFAULT_MODEL,
        temperature=args.temperature,
        max_steps=args.max_steps,
    )

    log_path = Path(args.log) if args.log else None
    start = time.time()
    try:
        result = run_agent(cfg, full_task, log_path=log_path,
                           on_step=_make_on_step(renderer, args.obs_limit,
                                                 transcript))
    except KeyboardInterrupt:
        _err("Interrupted.")
        return 1
    elapsed = time.time() - start

    if result is None:
        _err("ERROR: the agent produced no result (LLM failure or interruption).")
        return 1

    forced = bool(result.get("forced"))
    conclusion = str(result.get("conclusion", "")).strip()
    if not conclusion:
        # Forced verdicts occasionally come back without a `conclusion` key —
        # dump whatever the model produced so the log is never empty-handed.
        conclusion = json.dumps(
            {k: v for k, v in result.items() if k not in ("name", "forced")},
            ensure_ascii=False, indent=2,
        )

    renderer.conclusion(forced, elapsed, conclusion)

    # Consolidation runs on forced/failed outcomes too — "tried X, failed
    # because Y" is exactly the episode the next session needs most. Only a
    # None result (interruption, LLM death) leaves nothing reliable to record.
    if args.memory:
        renderer.memory_running()
        try:
            from skills.episode_consolidate.skill import (
                episode_consolidate_detailed,
            )
            res = episode_consolidate_detailed(
                transcript="\n".join(transcript),
                workspace=str(cwd), source="batch")
            renderer.memory_done(res.get("summary", ""))
        except Exception as e:
            renderer.memory_done(f"ERROR: {e}")

    return 2 if forced else 0


if __name__ == "__main__":
    sys.exit(main())
