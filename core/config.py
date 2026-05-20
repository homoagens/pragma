# config.py — global settings for the Pragma agent framework
#
# Configuration is read exclusively from environment variables.
# The recommended way to set them locally is to create a .env file
# in the project root (see .env.example) — it is loaded automatically.
#
# Nothing in this file should be committed with real credentials.

import os
from pathlib import Path

# Load .env file if present (requires python-dotenv in requirements.txt)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv is optional — env vars set by other means work fine

DEBUG = os.environ.get("PRAGMA_DEBUG", "").lower() in ("1", "true", "yes")

# ─────────────────────────────────────────────
# LLM PROVIDER
# ─────────────────────────────────────────────
# Supported values for LLM_PROVIDER:
#
#   "openai"    — any OpenAI-compatible endpoint (OpenAI, Ollama, Groq,
#                 Together, OpenRouter, DeepSeek, Mistral, vLLM, LiteLLM...)
#   "anthropic" — native Anthropic API (api.anthropic.com)
#
# Set LLM_BASE_URL to override the default endpoint for the provider.
# For Ollama (local): LLM_BASE_URL=http://localhost:11434/v1

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY  = os.environ.get("LLM_API_KEY",  "")

# ─────────────────────────────────────────────
# DEFAULT MODEL
# ─────────────────────────────────────────────
# The model name sent to the provider.
# Examples: llama3.2, gpt-4o-mini, claude-haiku-4-5

DEFAULT_MODEL       = os.environ.get("DEFAULT_MODEL", "llama3.2")
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "0.2"))

# ─────────────────────────────────────────────
# CODING MODEL (optional)
# ─────────────────────────────────────────────
# If set, the `code` skill uses this model instead of DEFAULT_MODEL.
# Useful to route code generation to a specialized model.
#
# Examples:
#   CODING_MODEL=qwen2.5-coder:14b   CODING_PROVIDER=openai  CODING_BASE_URL=http://localhost:11434/v1
#   CODING_MODEL=gpt-4o              CODING_PROVIDER=openai  CODING_BASE_URL=https://api.openai.com/v1  CODING_API_KEY=sk-...
#   CODING_MODEL=claude-sonnet-4-6   CODING_PROVIDER=anthropic  CODING_API_KEY=sk-ant-...

CODING_MODEL       = os.environ.get("CODING_MODEL", "")       # empty = use DEFAULT_MODEL
CODING_PROVIDER    = os.environ.get("CODING_PROVIDER", "")    # empty = use LLM_PROVIDER
CODING_BASE_URL    = os.environ.get("CODING_BASE_URL", "")    # empty = use LLM_BASE_URL
CODING_API_KEY     = os.environ.get("CODING_API_KEY", "")     # empty = use LLM_API_KEY
CODING_TEMPERATURE = float(os.environ.get("CODING_TEMPERATURE", "0.1"))
CODING_MAX_TOKENS  = int(os.environ.get("CODING_MAX_TOKENS",  "4096"))

# ─────────────────────────────────────────────
# GENERAL PARAMETERS
# ─────────────────────────────────────────────

MAX_TOKENS     = int(os.environ.get("MAX_TOKENS", "4096"))
TIMEOUT        = 300   # seconds — increase for slow or large-context models

# Quota of MAX_TOKENS available to LLM calls made INSIDE a skill
# (edit_file, code, llm_invoke, ...). Skills should never hardcode their
# own token budget — they read it from config so it scales with .env.
SKILL_MAX_TOKENS_RATIO = float(os.environ.get("SKILL_MAX_TOKENS_RATIO", "0.5"))
SKILL_MAX_TOKENS       = int(os.environ.get("SKILL_MAX_TOKENS",
                                            str(int(MAX_TOKENS * SKILL_MAX_TOKENS_RATIO))))

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
# (which would risk truncation regardless of formal budget). Override
# with WRITE_FILE_HARD_LIMIT in .env if you really want a different value.
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

# Character budget for conversation history carried across requests.
# 15% of context window — enough for 4-6 detailed exchanges.
HISTORY_MAX_CHARS = int(CONTEXT_WINDOW * 4 * 0.15)

# When compressing the message list, how many chars per message are kept
# in the text fed to the summarizer. Too low loses information; too high
# blows the summarizer's own token budget. 2000 is a balanced default.
MESSAGE_COMPRESS_TRUNC = int(os.environ.get("MESSAGE_COMPRESS_TRUNC", "2000"))

# Global learnings store (cross-thread semantic memory). Override to relocate.
LEARNINGS_PATH = os.environ.get(
    "LEARNINGS_PATH",
    str(Path.home() / ".pragma" / "learnings.json"),
)
# Number of recent learnings to recall and inject at the start of each task.
LEARNINGS_RECALL_TOP_K = int(os.environ.get("LEARNINGS_RECALL_TOP_K", "5"))
# If True, run session_reflect automatically after each successful task.
AUTO_REFLECT = os.environ.get("AUTO_REFLECT", "true").lower() in ("1", "true", "yes")

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


# ─────────────────────────────────────────────
# INTERNAL (not needed for standard providers)
# ─────────────────────────────────────────────
BACKEND_URL = os.environ.get("BACKEND_URL", "")
BACKEND_KEY = os.environ.get("BACKEND_KEY", "")
