# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# config.py — global settings for the Pragma agent framework
#
# Configuration is read exclusively from environment variables.
# The recommended way to set them locally is to create a .env file
# in the project root (see .env.example) — it is loaded automatically.
#
# Nothing in this file should be committed with real credentials.

import os
from pathlib import Path

# Load the .env file that sits next to this repo. python-dotenv is a hard
# dependency (it is in requirements.txt). If it is missing while a .env file
# exists, configuration would be silently ignored — fail loudly instead so
# the user knows their .env was not applied.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)
except ImportError as _e:
    if _ENV_FILE.exists():
        raise RuntimeError(
            f"python-dotenv is not installed but a .env file exists at "
            f"{_ENV_FILE}. Its settings would be silently ignored. "
            f"Install dependencies first: pip install -r requirements.txt"
        ) from _e
    # No .env present → environment variables set by other means still work.

DEBUG = os.environ.get("PRAGMA_DEBUG", "").lower() in ("1", "true", "yes")

# ─────────────────────────────────────────────
# MODEL PROFILE (optional) — one switch routes everything
# ─────────────────────────────────────────────
# PRAGMA_PROFILE=<name> selects a profile from models.json (next to .env,
# gitignored — it holds local ports; fallback: examples_memory/models.json):
#   { "27b": {"base_url": "http://127.0.0.1:8100/v1", "model": "Qwen3.6-27b"} }
# The profile overrides LLM_BASE_URL / DEFAULT_MODEL for THIS process, and sets
# PRAGMA_ARCHIVE_TAG=<name> so demo runs of an alternate model archive into
# their own subfolder. Resolved here (config is imported by everything), so it
# works identically for batch, the demos and the UI. No profile → no change.
PROFILE = os.environ.get("PRAGMA_PROFILE", "").strip()
if PROFILE:
    import json as _json
    os.environ.setdefault("PRAGMA_ARCHIVE_TAG", PROFILE)
    _ROOT = Path(__file__).resolve().parent.parent
    for _mj in (_ROOT / "models.json", _ROOT / "examples_memory" / "models.json"):
        try:
            _p = _json.loads(_mj.read_text(encoding="utf-8")).get(PROFILE)
        except Exception:
            _p = None
        if isinstance(_p, dict):
            if _p.get("base_url"):
                os.environ["LLM_BASE_URL"] = str(_p["base_url"])
            if _p.get("model"):
                os.environ["DEFAULT_MODEL"] = str(_p["model"])
            break

# ─────────────────────────────────────────────
# LLM ENDPOINT (OpenAI-compatible)
# ─────────────────────────────────────────────
# Pragma talks to a single OpenAI-compatible endpoint:
#     POST {LLM_BASE_URL}/chat/completions
# LLM_BASE_URL MUST end in /v1. Works with llama.cpp server, LM Studio,
# Ollama (/v1), vLLM, OpenAI, Groq, OpenRouter, DeepSeek, LiteLLM, ...
# Examples:
#   llama.cpp : http://127.0.0.1:8080/v1
#   LM Studio : http://127.0.0.1:1234/v1
#   Ollama    : http://127.0.0.1:11434/v1
# LLM_API_KEY is optional (local servers usually need none).

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "")

# ─────────────────────────────────────────────
# DEFAULT MODEL
# ─────────────────────────────────────────────
# The model name sent to the provider.
# Examples: llama3.2, gpt-4o-mini, claude-haiku-4-5

DEFAULT_MODEL       = os.environ.get("DEFAULT_MODEL", "llama3.2")

# ── Sampling ─────────────────────────────────────────────────────────────────
# TEMPERATURE IS ALWAYS SENT, the other three only when set. That asymmetry is
# the whole design, and it comes from how an OpenAI-compatible server resolves
# a request: a field present in the JSON body wins, a field absent falls back
# to the server's own launch-time default. So an unset knob here does not mean
# "some hidden Pragma value" — it means the server decides, which is where a
# sampling preset for a given model usually already lives.
#
# Temperature is the exception because determinism is not a preference here.
# The memory faculties ask for structured judgement (which fragments matter,
# what happened, what it means) and pass 0.0 explicitly; a benchmark campaign
# wants the task to be the variable and not the dice. Leaving temperature to
# the server would make both of those accidental, so it is stated.
#
# Note that at temperature 0 llama.cpp decodes greedily and top_k / top_p /
# min_p have no effect at all. Setting them is only meaningful together with a
# temperature above zero.
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "0.0"))


def _opt_float(name):
    """An optional sampling knob: a number when set, None when not."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _opt_int(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


TOP_K = _opt_int("TOP_K")
TOP_P = _opt_float("TOP_P")
MIN_P = _opt_float("MIN_P")

# The history summariser (memory.summarize), used by the ReAct compressor and by
# the UI worker. It had 0.2 written into memory.py since the first release, back
# when DEFAULT_TEMPERATURE was also 0.2 - so it was never a decision, it was the
# default spelled out. Lowering DEFAULT_TEMPERATURE to 0.0 left it agreeing with
# nothing, and invisible: it appears in no config, no banner, no manifest, and
# surfaced only by asking the server what it had last been sent.
#
# It matters more than a stray constant. Unlike the four memory faculties, which
# pass 0.0 and answer under a grammar, this one writes free prose while sampling,
# so it is the single non-deterministic call in an otherwise pinned run - and its
# output enters the context and shapes every step after it. Two identical runs
# that both compress diverge from that point.
#
# The value is deliberately UNCHANGED at 0.2: naming a number is safe, moving it
# is not. Greedy decoding of a long summary with no schema can loop, which is
# not something to discover mid-campaign. Try 0.0 between campaigns, not inside
# one.
SUMMARY_TEMPERATURE = float(os.environ.get("SUMMARY_TEMPERATURE", "0.2"))


def sampling_extras():
    """The optional samplers, as payload fields — only the ones actually set.

    top_k / min_p are llama.cpp extensions rather than OpenAI fields; a server
    that does not know them ignores them, which is the same outcome as not
    sending them, so there is nothing to guard against.
    """
    out = {}
    if TOP_K is not None:
        out["top_k"] = TOP_K
    if TOP_P is not None:
        out["top_p"] = TOP_P
    if MIN_P is not None:
        out["min_p"] = MIN_P
    return out


def sampling_line():
    """One human-readable line: what this process will actually send."""
    parts = [f"temp {DEFAULT_TEMPERATURE:g}"]
    for k, v in sampling_extras().items():
        parts.append(f"{k} {v:g}")
    if len(parts) == 1:
        parts.append("top_k/top_p/min_p from the server")
    return " / ".join(parts)

# The model the endpoint is ACTUALLY serving, resolved at runtime by
# llm_client.ping_models() via GET /models (llama.cpp reports the loaded
# model). Display and provenance (banner, episodes, demo meta) prefer this
# truth over the DEFAULT_MODEL label — labels can lie, the endpoint cannot.
SERVED_MODEL = ""

# ─────────────────────────────────────────────
# CODING MODEL (optional)
# ─────────────────────────────────────────────
# If set, the `code` skill uses this model instead of DEFAULT_MODEL.
# Useful to route code generation to a specialized model.
#
# Examples:
#   CODING_MODEL=qwen2.5-coder:14b   CODING_BASE_URL=http://localhost:11434/v1
#   CODING_MODEL=gpt-4o              CODING_BASE_URL=https://api.openai.com/v1  CODING_API_KEY=sk-...

CODING_MODEL       = os.environ.get("CODING_MODEL", "")       # empty = use DEFAULT_MODEL
CODING_BASE_URL    = os.environ.get("CODING_BASE_URL", "")    # empty = use LLM_BASE_URL
CODING_API_KEY     = os.environ.get("CODING_API_KEY", "")     # empty = use LLM_API_KEY
CODING_TEMPERATURE = float(os.environ.get("CODING_TEMPERATURE", "0.1"))
CODING_MAX_TOKENS  = int(os.environ.get("CODING_MAX_TOKENS",  "16384"))  # see MAX_TOKENS

# ─────────────────────────────────────────────
# GENERAL PARAMETERS
# ─────────────────────────────────────────────

# Output budget for one LLM reply. This is the ACTION channel's budget: the
# reply has to carry the whole content of a write_file, so it is the file
# size that sets the floor, not the prose.
#
# Why 16384 and not the old 4096. On the structural benchmark under the
# native protocol, the only two failing write_file calls out of 25 were
# generations cut off mid-string at exactly the old budget — 3.3 KB and
# 10.5 KB of arguments, both ending inside a token, neither malformed. A
# grammar cannot prevent that: it constrains what may be emitted, not how
# long the emission may run. llama-server itself sets no cap (n_predict=-1),
# so the ceiling was entirely ours, and the harnesses we compare against
# (opencode, pi) do not impose one either.
#
# It still has to fit: history compression caps the prompt at MAX_CHARS
# (~36k tokens of a 64k window), leaving room for a full 16k generation.
# On a smaller context, lower this together with CONTEXT_WINDOW.
#
# To reproduce the frozen evaluation corpus, set MAX_TOKENS=4096: that
# campaign ran on the old budget.
MAX_TOKENS     = int(os.environ.get("MAX_TOKENS", "16384"))

# How the agent's ACTION is carried, for the ReAct loop only.
#
#   text   : the model writes {"thought","action","args"} inside its reply and
#            Pragma parses it afterwards. Nothing constrains the generation.
#   native : the skills are sent as OpenAI `tools`. A server that compiles them
#            into a grammar constrains the sampler, so malformed arguments
#            cannot be produced rather than merely being detected.
#
# Measured on the structural benchmark, same two cases, same model:
#   text   : 93 write_file calls, 17 with unusable arguments (18%);
#            15 of 30 runs produced the requested figures.
#   native : 25 write_file calls, 2 with unusable arguments (8%), both of
#            them budget truncations rather than corruption; 6 of 6 runs
#            produced the figures.
# `native` costs roughly 3k more prompt tokens per request (the schemas
# replace a compact summary) and needs a server that implements tools —
# Pragma falls back to `text` automatically when it does not.
#
# This governs the ACTION channel only. The memory faculties keep their own
# text protocol either way, so the evaluation corpus stays comparable.
LLM_TOOL_PROTOCOL = os.environ.get("LLM_TOOL_PROTOCOL", "text").strip().lower()

# Seconds before an LLM HTTP call is abandoned. With a large output budget
# on a slow local model (a dense 27B+ partially offloaded can sit under
# 10 tok/s), a single long generation can legitimately take several
# minutes — raise via LLM_TIMEOUT instead of editing this file.
#
# Sized against MAX_TOKENS: 16k tokens at the ~40 tok/s a 27B dense reaches
# on one consumer GPU is already 400s, and a timeout that fires mid-write
# costs more than one that waits.
TIMEOUT        = int(os.environ.get("LLM_TIMEOUT", "900"))

# Budget for LLM calls made INSIDE a skill (edit_file, code, llm_invoke) and
# by the memory faculties (consolidator, curator, reconsolidator). Skills
# should never hardcode their own budget — they read it from config.
#
# Same budget as the action channel, and for a different reason. What these
# calls have to emit is short — a JSON verdict, a reformulated belief — but
# on a thinking model the reply is reasoning FIRST and JSON last, so a tight
# budget truncates exactly the part that matters and the faculty returns
# nothing usable. Their prompts are small (one episode plus a few beliefs),
# so there is context to spare: give them the room.
#
# This is not free. A larger budget does not only prevent truncation, it
# also lets a faculty write MORE — longer narratives, wordier beliefs. That
# is a change in what the memory contains, not just in how often it fails.
# To reproduce the frozen evaluation corpus, set SKILL_MAX_TOKENS=2048.
#
# SKILL_MAX_TOKENS_RATIO ties it to MAX_TOKENS instead, when set.
# 0.0 = unset, use the absolute default below.
SKILL_MAX_TOKENS_RATIO = float(os.environ.get("SKILL_MAX_TOKENS_RATIO", "0") or 0)
_skill_default = (int(MAX_TOKENS * SKILL_MAX_TOKENS_RATIO)
                  if SKILL_MAX_TOKENS_RATIO > 0 else MAX_TOKENS)
SKILL_MAX_TOKENS       = int(os.environ.get("SKILL_MAX_TOKENS", str(_skill_default)))

# The memory faculties read THIS one, so that the reasoning above can be
# revisited for them without touching the skills.
#
# The argument for one shared budget still holds, which is why the default
# here is SKILL_MAX_TOKENS and nothing changes until someone sets it. What
# does not hold is the COUPLING: raising the agent's output budget, a decision
# about writing files, silently widened the curator's too — and a curator
# spending six thousand tokens on a verdict of three lines is a session that
# waits minutes before its first step, on an endpoint where that can reach the
# timeout and fall back to the deterministic path for no reason anyone could
# name from the outside.
#
# Both directions cost something, so neither is the safe one:
#   too high — the faculty is free to ramble, the wait is real, and long
#              narratives change what the memory CONTAINS, not just its speed;
#   too low  — on a thinking model the reasoning eats the budget and the JSON
#              is truncated, which reads as a faculty that found nothing.
# Set it against your model, and prefer erring high on one that reasons.
MEMORY_MAX_TOKENS      = int(os.environ.get("MEMORY_MAX_TOKENS",
                                            str(SKILL_MAX_TOKENS)))

# Ask the chat template to skip the thinking phase, for the memory calls only.
#
# WHY IT IS WORTH ASKING. A curator picks three fragments from a numbered list
# and its output shape is already forced by a JSON schema. Measured against a
# reasoning model: 83 completion tokens and 8.6s with thinking, 17 tokens and
# 1.6s without, same answer. On a session that curates once per turn, that is
# the difference between memory you notice and memory you wait for.
#
# WHY IT IS OFF BY DEFAULT. It is not a speed setting, it is a change of
# faculty: a curator that does not deliberate may well select differently, and
# what the store ends up holding is the thing under study here. Opt in per
# session, and do not compare runs across the switch.
#
# WHY BOTH KEYS. Templates disagree on the name - `enable_thinking` is the
# common one, `thinking` is used by others. Probing two models showed one
# honouring both and the other honouring only `enable_thinking` while ignoring
# `thinking` in silence, so an extra key costs nothing while a missing one
# leaves thinking quietly on. A template that reads neither ignores both,
# which llm_client notices and reports.
#
# WHY THREE STATES AND NOT A BOOLEAN. The six faculties do not do the same
# kind of work, and the case for silencing them is not the same either.
#
#   SELECT  the curator picks fragments from a numbered list, the segmenter
#           partitions turns. Routing decisions, output already forced by a
#           schema, temperature 0. Deliberation here is mostly the prompt
#           restated - and a bad pick costs one mediocre turn.
#   WRITE   the consolidator composes a narrative, the abstractor generalises
#           a RULE from one episode, the reconsolidator revises a belief.
#           These compose rather than choose, and the abstractor's step is
#           inductive by nature. A bad generalisation is WRITTEN INTO the
#           store, recalled by later sessions, and shapes what the agent does
#           next: the error compounds instead of expiring.
#
# So the asymmetry is in the cost of being wrong, not in the tokens. "select"
# is the setting to reach for; "all" is for when you have measured that the
# writers do just as well without.
_NO_THINK = os.environ.get("MEMORY_NO_THINK", "").strip().lower()
if _NO_THINK in ("1", "true", "yes", "on"):
    _NO_THINK = "all"          # what the flag meant when it was a boolean
elif _NO_THINK in ("0", "false", "no", "off"):
    _NO_THINK = ""
MEMORY_NO_THINK = _NO_THINK if _NO_THINK in ("select", "write", "all") else ""


def memory_template_kwargs(kind="write"):
    """chat_template_kwargs for a memory call, or None to send no field.

    `kind` is "select" or "write" — which of the two groups above the calling
    faculty belongs to. It defaults to "write" so that a call site added later
    and left unmarked keeps its thinking: the conservative side of the switch
    is the one where being wrong is permanent.
    """
    if not MEMORY_NO_THINK:
        return None
    if MEMORY_NO_THINK != "all" and MEMORY_NO_THINK != kind:
        return None
    return {"enable_thinking": False, "thinking": False}

# write_file emits a soft warning in the observation when content exceeds
# this many bytes — the agent learns to prefer incremental edits.
WRITE_FILE_SOFT_LIMIT = int(os.environ.get("WRITE_FILE_SOFT_LIMIT", "8000"))

# write_file REFUSES content larger than this in a single call. Above this
# size, the JSON-encoded args of the LLM response are likely to exceed
# MAX_TOKENS and truncate, breaking the call.
#
# Auto-scales with MAX_TOKENS by default: bigger output budget → bigger
# files can travel through the JSON layer safely. Formula:
#     default = min(MAX_TOKENS * 2 bytes, 20_000)
# Rationale: HTML/code content escapes to ~1.5x JSON bytes; at ~3.5 bytes
# per token we get ~50% of MAX_TOKENS as safe content bytes. Hard ceiling
# at 20 KB so we never let a single write try to ship a hundred-KB blob
# (which would risk truncation regardless of formal budget). At the default
# MAX_TOKENS the ceiling is what binds, and that is on purpose: past 20 KB
# the right move is several writes, not a bigger budget. Override with
# WRITE_FILE_HARD_LIMIT in .env if you really want a different value.
_default_write_hard = min(int(MAX_TOKENS * 2), 20_000)
WRITE_FILE_HARD_LIMIT = int(os.environ.get(
    "WRITE_FILE_HARD_LIMIT", str(_default_write_hard),
))

# Observations longer than this get summarized in the conversation history
# (the actual return value is unaffected — only the message stored for
# the next LLM turn is compacted). 0 disables the feature.
OBSERVATION_SOFT_LIMIT = int(os.environ.get("OBSERVATION_SOFT_LIMIT", "12000"))

# Reasoning loop watchdog: reasoning-capable models occasionally get stuck
# in their <think> block, repeating the same paragraph forever without
# converging. The watchdog fingerprints recent reasoning chunks and aborts
# the stream when the same window has appeared too many times.
#   _WINDOW   : size of each fingerprint (chars). Big enough to be unique
#               in natural prose, small enough to catch loops.
#   _CHECK_EVERY : sample a new fingerprint every N reasoning chars.
#   _THRESHOLD: number of repetitions of the same fingerprint that triggers.
#   _ENABLED  : kill switch. Set false to disable the watchdog entirely.
REASONING_LOOP_WINDOW      = int(os.environ.get("REASONING_LOOP_WINDOW", "200"))
REASONING_LOOP_CHECK_EVERY = int(os.environ.get("REASONING_LOOP_CHECK_EVERY", "400"))
REASONING_LOOP_THRESHOLD   = int(os.environ.get("REASONING_LOOP_THRESHOLD", "3"))
REASONING_LOOP_ENABLED     = os.environ.get(
    "REASONING_LOOP_ENABLED", "true"
).lower() in ("1", "true", "yes")

# Action loop watchdog: even when the reasoning text doesn't repeat, small
# models often emit the SAME tool call with the SAME arguments turn after
# turn while observations keep returning ERROR. The agent's mental model of
# the system state has diverged from reality. This watchdog detects that
# pattern at the action layer and injects a coercive recovery hint that
# tells the model to STOP repeating and CHANGE STRATEGY (typically: read_file
# first to see the actual state).
#   _THRESHOLD : N identical (action, args) calls in a row, all returning
#                ERROR, before the hint fires.
#   _ENABLED   : kill switch.
ACTION_LOOP_THRESHOLD = int(os.environ.get("ACTION_LOOP_THRESHOLD", "3"))
ACTION_LOOP_ENABLED   = os.environ.get(
    "ACTION_LOOP_ENABLED", "true"
).lower() in ("1", "true", "yes")

# Error-rate watchdog: complements the strict action-loop above. Fires when
# the agent has been thrashing across DIFFERENT skills, all returning ERROR
# (e.g. tried replace_in_file, then edit_file, then insert_after, then
# write_file — all failed with arg / path errors). The strict watchdog
# misses this because no single (action,args) pair repeats. This one looks
# at the error RATE over a sliding window of recent steps.
#   _WINDOW    : how many recent actions to consider
#   _THRESHOLD : fraction of those that must be errors (0.0-1.0)
ERROR_RATE_WINDOW    = int(os.environ.get("ERROR_RATE_WINDOW", "5"))
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", "0.75"))

# Maximum number of ReAct loop steps before a forced verdict is requested.
MAX_STEPS = int(os.environ.get("MAX_STEPS", "15"))

# Model context window (tokens). Compression thresholds are derived from this.
# Override via .env if you run a model with a larger window (e.g. 131072 for
# Qwen3 with 128k context, or 200000 for Claude 3.x).
CONTEXT_WINDOW = int(os.environ.get("CONTEXT_WINDOW", "65536"))

# Memory compression thresholds (see memory.py).
# Compression triggers when EITHER threshold is exceeded:
#   - MAX_MESSAGES: total messages in the list
#   - MAX_CHARS:    total characters (token proxy; 1 token ≈ 4 chars)
MAX_MESSAGES     = int(os.environ.get("MAX_MESSAGES", "30"))
MAX_CHARS        = int(CONTEXT_WINDOW * 4 * 0.55)  # ~55% of context window in chars
MESSAGES_RECENT  = int(os.environ.get("MESSAGES_RECENT", "6"))

# A ceiling in characters on those recent messages, because MESSAGES_RECENT is
# a count and a count is not a size: six turns can be three hundred tokens or
# thirty thousand, and they were preserved either way. That left a hole no
# amount of compression could close - the messages that overflowed the window
# were exactly the ones nobody was allowed to touch. Anything past this budget
# is moved into the summarised half instead: still recent, no longer verbatim.
#
# A quarter of the window. In ordinary use it is never reached, so behaviour is
# unchanged; it exists for the run where one step returns something enormous.
RECENT_MAX_CHARS = int(os.environ.get(
    "RECENT_MAX_CHARS", str(int(CONTEXT_WINDOW * 4 * 0.25))))

# Character budget for conversation history carried across requests.
# 15% of context window — enough for 4-6 detailed exchanges.
HISTORY_MAX_CHARS = int(CONTEXT_WINDOW * 4 * 0.15)

# ── Live session: when a conversation outgrows the window ────────────────────
# A batch run that overflows is summarised. A conversation is not: its older
# turns are finished experiences, so they are CONSOLIDATED into episodes and
# leave the context as memory rather than as a blurred paraphrase.
#
# CHAT_COMPACT_CHARS is the trigger, in characters (~4 per token), measured
# over the whole message list between turns. At 50% of the window there is
# room left for the turn that follows plus the model's reply — compacting at
# the brink would mean compacting again immediately.
#
# CHAT_KEEP_TURNS are the most recent turns left verbatim. They are what makes
# "that table we discussed" still work right after a compaction; everything
# before them is reachable through the episodes just written.
CHAT_COMPACT_CHARS = int(os.environ.get(
    "CHAT_COMPACT_CHARS", str(int(CONTEXT_WINDOW * 4 * 0.50))))
CHAT_KEEP_TURNS = int(os.environ.get("CHAT_KEEP_TURNS", "3"))

# How much of what the model SAID survives into the transcript a turn is
# consolidated from. The batch default is 300 characters, which is right there:
# a thought is machinery, and five hundred steps of it would bury the work.
#
# A live session is told to answer in the conclusion and keep the thought to one
# line, so in the intended case this budget is never reached. It exists for the
# case where the model does it anyway - and it did, before it was told not to:
# a reply ending "one paper under review, two being written" was cut inside
# "due in scritt|ura", so the substance of the day never reached memory while
# the receipt arrived whole. What the model says has to survive into the episode
# whichever field it came out of; where it belongs is a matter for the prompt,
# not for a truncation that loses it silently.
CHAT_TRANSCRIPT_CHARS = int(os.environ.get("CHAT_TRANSCRIPT_CHARS", "2000"))

# When compressing the message list, how many chars per message are kept
# in the text fed to the summarizer. Too low loses information; too high
# blows the summarizer's own token budget. 2000 is a balanced default.
MESSAGE_COMPRESS_TRUNC = int(os.environ.get("MESSAGE_COMPRESS_TRUNC", "2000"))

# ─────────────────────────────────────────────
# STORAGE — single cross-platform home for everything Pragma persists
# ─────────────────────────────────────────────
# One folder holds it all: conversation threads, the learnings store, the
# log, and (in a frozen build) the uploaded .env. The default is a ".pragma"
# directory inside the user's home folder — writable WITHOUT admin rights on
# Windows, macOS and Linux, and the SAME path on every OS. Override the whole
# location with PRAGMA_DATA_DIR.
DATA_DIR = Path(os.environ.get("PRAGMA_DATA_DIR", str(Path.home() / ".pragma")))

# Conversation threads (one JSON file per conversation).
THREADS_DIR = DATA_DIR / "threads"

# Application log (JSON Lines, written by the log_event skill).
LOG_PATH = DATA_DIR / "pragma.log"

# Global learnings store (cross-thread semantic memory). Lives inside
# DATA_DIR; LEARNINGS_PATH can still be overridden on its own if needed.
LEARNINGS_PATH = os.environ.get("LEARNINGS_PATH", str(DATA_DIR / "learnings.json"))
# Number of recent learnings to recall and inject at the start of each task.
LEARNINGS_RECALL_TOP_K = int(os.environ.get("LEARNINGS_RECALL_TOP_K", "5"))
# If True, run session_reflect automatically after each successful task.
AUTO_REFLECT = os.environ.get("AUTO_REFLECT", "true").lower() in ("1", "true", "yes")

# ─────────────────────────────────────────────
# MEMORY — episodic store + semantic assertions
# ─────────────────────────────────────────────
# Episodic memory: one JSON file per consolidated session episode
# (written by the episode_consolidate skill, retrieved by recall_episodes).
EPISODES_DIR = DATA_DIR / "episodes"

# Salience composition. An episode's initial salience is
#   base + surprise_weight * n_surprises + importance_weight * importance
# clamped to [.., cap]. The book's salience is "unexpected, IMPORTANT, or
# recurrent": surprises capture the unexpected, `importance` (judged by the
# consolidator, 0-1) captures the rest — so a persistent-but-unsurprising
# fact (a student's weak spot "to review", a decision that will matter) can
# outweigh a routine session that happened to hit a tool hiccup.
SALIENCE_BASE             = float(os.environ.get("SALIENCE_BASE", "0.30"))
SALIENCE_SURPRISE_WEIGHT  = float(os.environ.get("SALIENCE_SURPRISE_WEIGHT", "0.12"))
SALIENCE_IMPORTANCE_WEIGHT = float(os.environ.get("SALIENCE_IMPORTANCE_WEIGHT", "0.40"))
SALIENCE_CAP              = float(os.environ.get("SALIENCE_CAP", "0.95"))

# How many episodes recall_episodes returns by default.
EPISODES_RECALL_TOP_K = int(os.environ.get("EPISODES_RECALL_TOP_K", "3"))

# Score bonus for episodes born in the same workspace as the current task
# (episodes from other projects can still surface, but local ones win ties).
EPISODE_WORKSPACE_BOOST = int(os.environ.get("EPISODE_WORKSPACE_BOOST", "2"))

# Semantic prudence. A new assertion requires at least this many distinct
# source episodes ("one swallow does not make a summer"): a pattern seen
# once is an anecdote, seen twice it starts to be knowledge.
SEMANTIC_MIN_SOURCES = int(os.environ.get("SEMANTIC_MIN_SOURCES", "2"))
# Confidence dynamics: +bonus on each confirmation (cap 0.95), -malus on
# each contradiction (floor 0.05). A single contradiction must NOT retire
# consolidated knowledge — only repeated, independent ones do.
SEMANTIC_CONFIRM_BONUS        = float(os.environ.get("SEMANTIC_CONFIRM_BONUS", "0.1"))
SEMANTIC_CONTRADICT_MALUS     = float(os.environ.get("SEMANTIC_CONTRADICT_MALUS", "0.2"))
SEMANTIC_RETIRE_CONTRADICTIONS = int(os.environ.get("SEMANTIC_RETIRE_CONTRADICTIONS", "2"))

# ── Reconsolidation (Stage 3) ──
# Recall is read-modify-write of MEANING, never of facts. When a new session
# is consolidated, the thematically closest past episodes are re-read and
# their `interpretation` may be rewritten in the light of the novelty — the
# `narrative` (the facts) is frozen. At the semantic layer, a belief that has
# accumulated enough independent contradictions is REFORMULATED (its text
# rewritten to fit the evidence) rather than merely retired. Both rewrites are
# admitted only when still supported by the frozen facts / cited sources
# (the anti-confabulation guard), and touch only the evolving side of memory,
# never the constitutive core. Set RECONSOLIDATION_ENABLED=false to disable.
RECONSOLIDATION_ENABLED = os.environ.get(
    "RECONSOLIDATION_ENABLED", "true").lower() in ("1", "true", "yes")
# How many thematically-close episodes to re-read per consolidation.
RECONSOLIDATE_MAX_EPISODES = int(os.environ.get("RECONSOLIDATE_MAX_EPISODES", "3"))
# A belief is reformulated once it reaches this many independent contradictions
# (the same threshold that used to retire it: reformulation is now the primary
# response, retirement the fallback when no reformulation is defensible).
# Defaults to SEMANTIC_RETIRE_CONTRADICTIONS.
RECONSOLIDATE_REFORMULATE_AT = int(os.environ.get(
    "RECONSOLIDATE_REFORMULATE_AT", str(SEMANTIC_RETIRE_CONTRADICTIONS)))
# Bridge A→B: episodic reconsolidation feeds semantic reformulation. When at
# least this many of a belief's SOURCE episodes were reinterpreted in the same
# session, the belief is a reformulation candidate — even if the abstractor
# emitted no explicit contradiction. The robust episodic signal drives the
# fragile semantic one; on this path a belief is never retired, only rewritten.
RECONSOLIDATE_BRIDGE_MIN_SOURCES = int(os.environ.get(
    "RECONSOLIDATE_BRIDGE_MIN_SOURCES", "2"))

# Max chars of a project PRAGMA.md (user-authored instructions) injected
# verbatim into the task by runners that support it.
PRAGMA_MD_MAX_CHARS = int(os.environ.get("PRAGMA_MD_MAX_CHARS", "4000"))

# ── Context curator ──
# The knowledge zone of the context is not filled mechanically: a dedicated
# LLM invocation (the curator) selects, from a keyword-prefiltered candidate
# pool, the memory fragments that are genuinely relevant to the task and
# orders them by usefulness. Set CURATOR_ENABLED=false to fall back to the
# plain deterministic top-k injection.
CURATOR_ENABLED = os.environ.get(
    "CURATOR_ENABLED", "true").lower() in ("1", "true", "yes")
# How wide the deterministic prefilter casts its net before the LLM chooses.
CURATOR_CANDIDATES_EPISODES  = int(os.environ.get("CURATOR_CANDIDATES_EPISODES", "10"))
CURATOR_CANDIDATES_LEARNINGS = int(os.environ.get("CURATOR_CANDIDATES_LEARNINGS", "8"))
# Cap on how many fragments the curator may place on the desk.
CURATOR_MAX_FRAGMENTS = int(os.environ.get("CURATOR_MAX_FRAGMENTS", "6"))

# How much of a recalled episode is actually shown, per field. These two are
# ALSO quoted to the consolidator and the reconsolidator when they write, so
# the writer and the reader agree on a length: before, the consolidator
# averaged 248 chars of interpretation against a 200-char reader, so half of
# every meaning was generated only to be cut mid-sentence and never read.
#
# One number each, here, for both sides — a cap that lives in two files
# drifts apart the first time someone edits one of them.
#
# They are small on purpose. A memory is a pill, not a treatise: what is
# recalled has to fit beside the actual task without crowding it out, and at
# CURATOR_MAX_FRAGMENTS fragments these bound the whole recall at ~3 KB
# however large the store grows.
MEMORY_NARRATIVE_CHARS      = int(os.environ.get("MEMORY_NARRATIVE_CHARS", "400"))
MEMORY_INTERPRETATION_CHARS = int(os.environ.get("MEMORY_INTERPRETATION_CHARS", "200"))

# Whether the memory faculties constrain their JSON with a schema. Only has
# an effect on the native protocol, which is what carries schemas at all.
#
# Exists so the schema can be ablated WITHOUT changing the action channel:
# turning LLM_TOOL_PROTOCOL back to text would move both at once, and the
# question "do constrained faculties change what memory holds?" needs the
# action channel held constant. Set MEMORY_SCHEMA=0 for the unconstrained arm.
MEMORY_SCHEMA = os.environ.get("MEMORY_SCHEMA", "1").strip().lower() not in (
    "0", "false", "no", "off")

# ── Forgetting (episodic store) ──
# An episode's EFFECTIVE salience decays exponentially with the time since
# it was last recalled (or created): eff = salience * 0.5^(age_days /
# half_life). Recalling an episode resets its age and reinforces it — the
# decay is reversible, exactly like human forgetting. A very salient
# episode resists longer than a routine one by construction.
# Set the half-life to 0 to disable decay entirely.
EPISODE_DECAY_HALF_LIFE_DAYS = float(
    os.environ.get("EPISODE_DECAY_HALF_LIFE_DAYS", "30"))

# Below this effective salience an episode is moved to the dormant zone
# (episodes/dormant/): out of active recall and out of the abstraction
# pass, but still on disk and revivable if a future query needs it.
EPISODE_DORMANT_THRESHOLD = float(
    os.environ.get("EPISODE_DORMANT_THRESHOLD", "0.15"))

# True deletion happens only after an episode has been dormant this many
# days AND nothing references it (links from active episodes, sources of
# semantic assertions). 0 = never hard-delete (default: forgetting means
# inaccessibility, not destruction — opt in explicitly if disk matters).
EPISODE_DELETE_AFTER_DAYS = int(
    os.environ.get("EPISODE_DELETE_AFTER_DAYS", "0"))

# ─────────────────────────────────────────────
# SELF-INTEGRITY GUARD
# ─────────────────────────────────────────────
# Pragma must never modify its own files during a session. The
# file-mutating skills (write_file, edit_file, append_file, insert_*,
# replace_in_file*, ...) call self_modify_guard() before touching a path
# and refuse any write anywhere inside Pragma's own repository.
#
# The repository root is detected automatically from this file's location
# at runtime (Path(__file__)), so it is correct on every machine regardless
# of where the repo was cloned — no path is hardcoded.
#
# This is the deterministic safety net behind the soft "## Self-integrity"
# rule in the system prompt. Set PRAGMA_ALLOW_SELF_MODIFY=true ONLY if you
# are intentionally developing Pragma itself through a Pragma session.
ALLOW_SELF_MODIFY = os.environ.get(
    "PRAGMA_ALLOW_SELF_MODIFY", ""
).lower() in ("1", "true", "yes")

# Pragma's own repository root: this file is core/config.py, so the root
# is two levels up. Resolved at import time → absolute, machine-independent.
_PRAGMA_ROOT = Path(__file__).resolve().parent.parent


def self_modify_guard(path: str) -> str | None:
    """Return an ERROR string if `path` points anywhere inside Pragma's own
    repository, else None.

    Deterministic safety net: stops Pragma from creating, editing, patching
    or deleting any file within its own installation — source code, configs,
    UI, scripts, the lot. Honored by every file-mutating skill. Bypassed only
    when ALLOW_SELF_MODIFY is true (developer mode).

    The repo root is derived from this module's path, so the check works
    identically wherever the repository lives on disk.
    """
    # ── PRAGMA.md is the user's project contract — NEVER writable ──
    # It carries user-authored instructions (including standing
    # authorizations) that runners inject into the task. If the agent could
    # create, edit or delete it, it could grant ITSELF permissions. This
    # check is independent of ALLOW_SELF_MODIFY: not even developer mode
    # unlocks it — the file is edited by the user, by hand, or not at all.
    try:
        if Path(path).name.upper() == "PRAGMA.MD":
            return (
                f"ERROR: refused — '{path}' is a PRAGMA.md project-"
                f"instructions file. PRAGMA.md is authored by the USER and "
                f"is read-only for the agent: it must never be created, "
                f"modified or deleted in a session. If its content should "
                f"change, tell the user what to change and let them edit "
                f"it themselves. This is a hard guard — do not retry or "
                f"work around it."
            )
    except Exception:
        pass

    if ALLOW_SELF_MODIFY:
        return None
    try:
        target = Path(path).resolve()
    except Exception:
        return None  # unresolvable path — let the skill report its own error
    try:
        if target == _PRAGMA_ROOT or _PRAGMA_ROOT in target.parents:
            return (
                f"ERROR: refused — '{path}' is inside Pragma's own repository "
                f"({_PRAGMA_ROOT}). Pragma never modifies its own files; this "
                f"is a hard safety guard, not a recoverable error — do not "
                f"retry or look for a workaround. If a developer genuinely "
                f"needs to edit Pragma itself, they must do it with a normal "
                f"editor outside a Pragma session (or set "
                f"PRAGMA_ALLOW_SELF_MODIFY=true in .env)."
            )
    except Exception:
        pass
    return None
