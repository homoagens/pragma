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
DEFAULT_TEMPERATURE = float(os.environ.get("DEFAULT_TEMPERATURE", "0.2"))

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
CODING_MAX_TOKENS  = int(os.environ.get("CODING_MAX_TOKENS",  "4096"))

# ─────────────────────────────────────────────
# GENERAL PARAMETERS
# ─────────────────────────────────────────────

MAX_TOKENS     = int(os.environ.get("MAX_TOKENS", "4096"))

# Seconds before an LLM HTTP call is abandoned. With a large output budget
# on a slow local model (a dense 27B+ partially offloaded can sit under
# 10 tok/s), a single long generation can legitimately take several
# minutes — raise via LLM_TIMEOUT instead of editing this file.
TIMEOUT        = int(os.environ.get("LLM_TIMEOUT", "300"))

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
