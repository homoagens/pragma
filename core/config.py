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
# THE ENDPOINT DECIDES THE MODEL
# ─────────────────────────────
# There used to be a PRAGMA_PROFILE here, naming an entry in a gitignored
# models.json that overrode LLM_BASE_URL and DEFAULT_MODEL together. It is gone,
# because on a single-model server it could not do what it promised: llama.cpp
# serves whatever is loaded and ignores the "model" field of the request, so a
# profile only relabelled the same endpoint. In practice every profile pointed
# at one local port, and which model answered was decided by what was listening
# there - never by the profile.
#
# So the endpoint is the whole choice. Point LLM_BASE_URL at the server you
# want (configure, or LLM_BASE_URL per window) and the model follows. What the
# endpoint is really serving is resolved at runtime into SERVED_MODEL, which is
# what the banners and the episodes record - a label can lie the moment another
# model is loaded on the same port, and the endpoint cannot.
#
# PRAGMA_ARCHIVE_TAG still exists and is still what keeps an alternate model's
# runs in their own archive subfolder; it is now set directly instead of being
# inferred from a profile name.
PROFILE = ""

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
# DEFAULT_TEMPERATURE=server hands the temperature to the endpoint as well,
# by omitting the field from the request instead of sending a number. Until
# now three of the four sampling parameters honoured "unset means the server
# decides" and this one did not: it was always sent, so a server's own
# temperature could never apply - and at 0.0 the decoding is greedy, which
# makes the other three inert however the server had set them.
#
# The faculties are unaffected. Curator, consolidator, abstractor and
# reconsolidator pass temperature=0.0 explicitly at the call site, so the
# store stays deterministic whatever this says.
#
# Empty still means 0.0, not "server": changing what an unset value means
# would silently move every existing setup the day it upgraded.
_temp_raw = os.environ.get("DEFAULT_TEMPERATURE", "0.0").strip()
DEFAULT_TEMPERATURE = None if _temp_raw.lower() == "server" else float(_temp_raw)
# A profile carries a temperature of its own; it is applied below, once the
# table has been read. A project that also named a temperature keeps it: a
# number someone typed beats a number someone chose from a list.
_TEMP_DECLARED = bool(os.environ.get("DEFAULT_TEMPERATURE", "").strip())


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


# ── Sampling profiles ─────────────────────────────────────────────────────────
# The knobs travel in every request, so what a request does not send is what
# the server was started with. WHICH knobs is a property of the ENDPOINT, and
# it is written beside its address in ~/.pragma/endpoints.json - one file, one
# page, one place to look:
#
#     "kind": "thinking" | "instruct"     what the model is
#     "work": "general"  | "coding"       what this endpoint is used for
#     "sampling": {"thinking": {"general": {...}, "coding": {...}},
#                  "instruct": {"general": {...}, "coding": {...}}}
#
# An endpoint that says nothing sends nothing, and the server decides
# everything - which is what it was started to do. That is the default, and
# also what /configure calls "standard".
#
# The two words are the endpoint's because the server is what they describe:
# the machine at that address is running one model, started one way, and no
# project changes that by opening. A project can still override either for
# its own run (AGENT_THINK, SAMPLING_PROFILE) - it is the same harness, and
# the one who set it up is the one asking.
#
# MEASURED on llama.cpp (Qwen3.6-35B-A3B, 2026-09-21), one knob at a time:
# temperature, top_k, top_p, min_p, presence_penalty, frequency_penalty and
# repeat_penalty all change the reply. `repetition_penalty` does NOT: that is
# the HuggingFace name and this server drops it in silence, which is why the
# tables people copy from model cards have to be translated on the way in.
# endpoints.KNOBS is that translated list, and nothing outside it is written.
#
# server : send none of them, whatever the endpoint says
# greedy : temperature 0, nothing else - the paper's runs
# manual : DEFAULT_TEMPERATURE / TOP_K / TOP_P / MIN_P, set one by one
# general | coding : that row of the endpoint's own table
SAMPLING_PROFILE = os.environ.get("SAMPLING_PROFILE", "").strip().lower()


def _agent_entry() -> dict:
    """The agent endpoint's catalogue entry, or {}. Looked up every time: the
    endpoint can change with /configure while a conversation is running."""
    try:
        import endpoints
        return endpoints.entry_for_role("agent")
    except Exception:
        return {}


def agent_endpoint_name() -> str:
    """What the catalogue calls the endpoint the agent talks to, or ""."""
    try:
        import endpoints
        return endpoints.for_role("agent").name or ""
    except Exception:
        return ""


def agent_thinking() -> bool:
    """Does the agent reason before answering?

    The endpoint knows: it is running one model and that model either reasons
    or does not, so `kind` in the catalogue is the answer for every project
    that talks to it. AGENT_THINK still wins where it is set, for the run that
    wants the other behaviour out of a model that can do both.
    """
    if _AGENT_THINK in ("on", "1", "true", "yes"):
        return True
    if _AGENT_THINK in ("off", "0", "false", "no"):
        return False
    return _agent_entry().get("kind") == "thinking"


def agent_flavour() -> str:
    """What this endpoint is being used for: general work, or coding."""
    if SAMPLING_PROFILE in ("general", "coding"):
        return SAMPLING_PROFILE
    work = _agent_entry().get("work")
    return work if work in ("general", "coding") else "general"


def agent_profile() -> tuple[str, dict]:
    """(name, knobs) for this project's agent calls, or ("", {}).

    The name is the two words and whose table they came from, because that is
    what a status line has to be able to say: `thinking . coding (montecucco)`.
    """
    if SAMPLING_PROFILE in ("server", "greedy", "manual"):
        return "", {}
    entry = _agent_entry()
    if not entry.get("sampling"):
        return "", {}
    try:
        import endpoints
        kind = "thinking" if agent_thinking() else "instruct"
        work = agent_flavour()
        knobs = endpoints.sampling_row(entry, kind, work)
    except Exception:
        return "", {}
    if not knobs:
        return "", {}
    where = agent_endpoint_name()
    return f"{kind} . {work}" + (f" ({where})" if where else ""), knobs


def sampling_extras():
    """The optional samplers, as payload fields — only the ones actually set.

    A profile answers for all of them at once. Without one it is the four
    knobs set by hand, as before.

    top_k / min_p are llama.cpp extensions rather than OpenAI fields; a server
    that does not know them ignores them, which is the same outcome as not
    sending them, so there is nothing to guard against.
    """
    _, knobs = agent_profile()
    if knobs:
        knobs.pop("temperature", None)              # that one travels on its own
        return {k: v for k, v in knobs.items() if v is not None}
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
    name, _ = agent_profile()
    if name:
        sent = ", ".join(f"{k} {v:g}" for k, v in sorted(sampling_extras().items()))
        t = agent_temperature()
        temp = "temp from the server" if t is None else f"temp {t:g}"
        return f"{name} . {temp} / {sent}" if sent else f"{name} . {temp}"
    if DEFAULT_TEMPERATURE is None:
        parts = ["temp from the server"]
    else:
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

# HOW THE AGENT'S ACTION IS CARRIED. As OpenAI `tools`, always: there is no
# setting here any more, because there is no second answer.
#
# There used to be. `text` had the model write {"thought","action","args"}
# inside its reply and Pragma parse it out afterwards, with nothing
# constraining the generation - so every quote and newline of a file being
# written was the model's own escaping work, and a mistake was unrecoverable
# by the time it showed. Measured on the structural benchmark, same two cases,
# same model:
#   text   : 93 write_file calls, 17 with unusable arguments (18%);
#            15 of 30 runs produced the requested figures.
#   native : 25 write_file calls, 2 with unusable arguments (8%), both of
#            them budget truncations rather than corruption; 6 of 6 runs
#            produced the figures.
# The gap widens as the model gets smaller: a sparse MoE with a few billion
# active parameters is good enough to write the file and not good enough to
# escape it, and on `text` those are the same task.
#
# Keeping the loser as an option cost more than it saved: a second prompt to
# maintain, a second palette (the base64 skills existed only to work around
# the escaping), a second set of failures to reason about, and a raw-format
# parser in react.py that knew one model family's markup by heart. The frozen
# evaluation corpus was produced on `text` and is reproducible from the tagged
# commit, which is where a retired protocol belongs.
#
# An endpoint that does not implement tools cannot run the agent, and says so
# on the first step. The memory faculties are untouched: they ask for a domain
# JSON object, not for a tool choice.

# Seconds before an LLM HTTP call is abandoned. With a large output budget
# on a slow local model (a dense 27B+ partially offloaded can sit under
# 10 tok/s), a single long generation can legitimately take several
# minutes — raise via LLM_TIMEOUT instead of editing this file.
#
# Sized against MAX_TOKENS: 16k tokens at the ~40 tok/s a 27B dense reaches
# on one consumer GPU is already 400s, and a timeout that fires mid-write
# costs more than one that waits.
TIMEOUT        = int(os.environ.get("LLM_TIMEOUT", "900"))

# Budget for LLM calls made INSIDE a skill (vision_interpret) and
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


# THE AGENT'S SWITCH. Normally the endpoint's, because the endpoint is running
# the model and knows whether it reasons: /configure writes that as `kind`,
# and agent_thinking() reads it. AGENT_THINK overrides it for one run, either
# way, which is why it is kept as the raw word rather than a boolean - "unset"
# and "off" are different answers here.
_AGENT_THINK = os.environ.get("AGENT_THINK", "").strip().lower()
AGENT_THINK = _AGENT_THINK in ("on", "1", "true", "yes")

# server and greedy are decided here, because they are decided by the word
# alone. A profile's temperature is not: which table it comes from depends on
# the model the endpoint turns out to be serving, which nothing knows yet.
if SAMPLING_PROFILE == "server":
    DEFAULT_TEMPERATURE = None                      # the endpoint decides it too
elif SAMPLING_PROFILE == "greedy":
    DEFAULT_TEMPERATURE = 0.0


def agent_temperature():
    """The temperature an agent call travels with when the caller names none.

    A number someone typed wins over one chosen from a list, so a project
    that set DEFAULT_TEMPERATURE keeps it whatever profile it also picked.
    """
    if not _TEMP_DECLARED:
        _, knobs = agent_profile()
        if knobs.get("temperature") is not None:
            return float(knobs["temperature"])
    return DEFAULT_TEMPERATURE




def _thinking(on: bool) -> dict:
    # Both spellings: which key a chat template reads is a property of the
    # model, and a template that reads neither ignores both in silence.
    return {"enable_thinking": on, "thinking": on}


def agent_template_kwargs():
    """chat_template_kwargs for the agent's calls: always explicit.

    Explicit because a server's default is a choice made somewhere else. A
    server that thinks by default made "off" impossible to ask for; one that
    does not made "on" impossible. Saying it on every call makes the setting
    mean the same thing against either.
    """
    return _thinking(agent_thinking())


def memory_template_kwargs(kind="write"):
    """chat_template_kwargs for a memory call: always explicit, true or false.

    `kind` is "select" or "write" — which of the two groups above the calling
    faculty belongs to. It defaults to "write" so that a call site added later
    and left unmarked keeps its thinking: the conservative side of the switch
    is the one where being wrong is permanent.

    It used to return None - send nothing - for the calls meant to think,
    which only worked against a server that thinks by default.
    """
    silenced = MEMORY_NO_THINK == "all" or MEMORY_NO_THINK == kind
    return _thinking(not silenced)


# HOW A MEMORY CALL PICKS ITS WORDS. Temperature 0 was the rule, for a store
# that reproduces and a benchmark that measures the agent rather than the dice.
# It stays the rule for calls that do not reason. A call that reasons at
# temperature 0 is what reasoning models are not trained for: greedy decoding
# makes them repeat a paragraph until the budget runs out. So those use the
# model's thinking preset, with a fixed seed - measured on montecucco, two
# calls with the same seed gave the same reasoning and the same answer.
#   preset  thinking calls sample with the preset and MEMORY_SEED (default)
#   greedy  every memory call at temperature 0, as the paper's runs were
# Separate from DEFAULT_TEMPERATURE on purpose: warming the conversation must
# never warm the consolidator behind its back.
_MS = os.environ.get("MEMORY_SAMPLING", "").strip().lower()
MEMORY_SAMPLING = _MS if _MS in ("preset", "greedy") else "preset"
MEMORY_SEED = int(os.environ.get("MEMORY_SEED", "") or 42)
MEMORY_THINK_PRESET = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}

# A reasoning that goes on and on without an answer starting is stopped at
# this many characters and the call asked again without thinking. The loop
# guard only sees a paragraph repeated word for word; a model circling in new
# words each time never trips it. About 4 000 tokens: a healthy consolidation
# on montecucco reasoned 1 000 to 1 700. 0 = no cap.
MEMORY_THINK_BUDGET = int(os.environ.get("MEMORY_THINK_BUDGET", "") or 16000)


def memory_call(kind="write") -> dict:
    """The arguments a memory call passes to call_llm about how to think:
    temperature, template_kwargs (the thinking switch) and sampling."""
    template = memory_template_kwargs(kind)
    if template["enable_thinking"] and MEMORY_SAMPLING == "preset":
        sampling = dict(MEMORY_THINK_PRESET)
        temperature = sampling.pop("temperature")
        sampling["seed"] = MEMORY_SEED
        return {"temperature": temperature, "template_kwargs": template, "sampling": sampling}
    return {"temperature": 0.0, "template_kwargs": template, "sampling": None}

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
# The faculties' calls stream, so their reasoning can be watched and the
# loop guard below can stop it. LLM_STREAM_CALLS=0 goes back to the blocking
# request for every call_llm, for a server whose streaming misbehaves.
STREAM_CALLS = os.environ.get("LLM_STREAM_CALLS", "1").strip().lower() not in ("0", "false", "no", "off")

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
# (e.g. tried replace_in_file, then apply_patch, then insert_after, then
# write_file — all failed with arg / path errors). The strict watchdog
# misses this because no single (action,args) pair repeats. This one looks
# at the error RATE over a sliding window of recent steps.
#   _WINDOW    : how many recent actions to consider
#   _THRESHOLD : fraction of those that must be errors (0.0-1.0)
ERROR_RATE_WINDOW    = int(os.environ.get("ERROR_RATE_WINDOW", "5"))
ERROR_RATE_THRESHOLD = float(os.environ.get("ERROR_RATE_THRESHOLD", "0.75"))

# Maximum number of ReAct loop steps before a forced verdict is requested.
MAX_STEPS = int(os.environ.get("MAX_STEPS", "15"))

# Model context window (tokens). Compression thresholds are derived from this,
# so a wrong value does not degrade gracefully: Pragma keeps talking until the
# server refuses the request, having compacted for a window it never had.
#
# EMPTY MEANS ASK THE SERVER, the same convention DEFAULT_MODEL already uses.
# The endpoint knows the answer exactly - llama.cpp reports n_ctx PER SLOT, so
# it has already divided by --parallel and there is no arithmetic here to get
# wrong. Restart the server with a different -c or -np and the next window
# picks it up.
#
# The order is declared-beats-discovered: a project's ContextWindow, then
# CONTEXT_WINDOW in .env, then the server, then this default. Someone who
# writes a number means it.
_CTX_DEFAULT = 65536

# How long a connection may take to be accepted before an endpoint counts as
# not connected. Measured, not guessed: on Windows a closed port does not
# refuse at once, the connect is retried for about two seconds, and every
# startup path used to pay that once per question - the context probe at
# import, then the ping, in the briefing and again in the conversation. With
# the endpoint down the launcher sat on a blank screen long enough to look
# stuck. A second is plenty for anything on the same machine or LAN.
ENDPOINT_PROBE_TIMEOUT = float(os.environ.get("ENDPOINT_PROBE_TIMEOUT", "1.0"))
_REACHABLE: dict = {}


def endpoint_reachable(base_url: str, timeout: float | None = None) -> bool:
    """Does anything accept a connection at this endpoint? A bare TCP connect.

    The one quick test every caller asks before a real request, so that "not
    connected" costs at most ENDPOINT_PROBE_TIMEOUT. The answer is kept for a
    few seconds, because one process routinely asks twice in a row. It says
    nothing about whether the server works; the request that follows does.
    """
    import socket
    import time
    from urllib.parse import urlsplit
    try:
        parts = urlsplit((base_url or "").strip())
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except Exception:
        return False
    if not host:
        return False
    now = time.monotonic()
    hit = _REACHABLE.get((host, port))
    if hit and now - hit[0] < 5.0:
        return hit[1]
    try:
        socket.create_connection(
            (host, port), timeout=timeout or ENDPOINT_PROBE_TIMEOUT).close()
        ok = True
    except OSError:
        ok = False
    _REACHABLE[(host, port)] = (now, ok)
    return ok


def _endpoint_context_window() -> int:
    """n_ctx from an OpenAI-compatible server's /props, or 0.

    Deliberately a bare request rather than llm_client: that module imports
    this one, and a config that needs the client to configure itself is a
    circular import waiting to happen. Short timeout, because this runs at
    import time in every process that reads config - including ones with no
    interest in a context window at all.

    The window is the AGENT's: compaction bounds the agent's history, and the
    faculties send prompts far smaller than any window. With an endpoint
    catalogue that is the endpoint assigned to `agent`; a catalogue that
    cannot be read gives 0 here, and the error surfaces on the first call.
    """
    base = (os.environ.get("LLM_BASE_URL") or LLM_BASE_URL or "").strip()
    key = os.environ.get("LLM_API_KEY") or LLM_API_KEY
    try:
        # Imported here, not at the top: endpoints imports this module, and
        # by the time this runs everything it reads from config is defined.
        import endpoints
        catalogue, error = endpoints.load_catalogue()
        if error:
            return 0
        if catalogue is not None:
            agent = endpoints.for_role("agent")
            base, key = agent.base_url, agent.api_key
    except ImportError:
        pass
    if not base:
        return 0
    if not endpoint_reachable(base):
        return 0
    root = base[:-3] if base.rstrip("/").endswith("/v1") else base
    try:
        import requests
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        r = requests.get(root.rstrip("/") + "/props", headers=headers,
                         timeout=1.5)
        if r.status_code != 200:
            return 0
        gen = (r.json() or {}).get("default_generation_settings") or {}
        return int(gen.get("n_ctx") or 0)
    except Exception:
        return 0


_ctx_declared = os.environ.get("CONTEXT_WINDOW", "").strip()
CONTEXT_WINDOW_SOURCE = "declared"
if _ctx_declared:
    CONTEXT_WINDOW = int(_ctx_declared)
elif os.environ.get("PRAGMA_NO_ENDPOINT_PROBE", "").strip().lower() in (
        "1", "true", "yes"):
    CONTEXT_WINDOW = _CTX_DEFAULT
    CONTEXT_WINDOW_SOURCE = "default"
else:
    _found = _endpoint_context_window()
    CONTEXT_WINDOW = _found or _CTX_DEFAULT
    CONTEXT_WINDOW_SOURCE = "endpoint" if _found else "default"

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

# The same trigger, in TOKENS THE SERVER COUNTED, which is what it becomes as
# soon as one request has been answered. The characters above are the estimate
# used until then, and an estimate is all they can be: measured against this
# model's own tokenizer, 4 chars per token holds for English prose (4.02) and
# is generous for Italian (4.68), but Python source runs at 3.16 and a tool
# observation full of JSON, numbers and paths at 1.23. A conversation about
# code therefore sat near 70% of the window while the page said 50%, and the
# margin that looked like caution was the error bar.
#
# usage.prompt_tokens comes back with every reply, so after the first turn the
# real size is known exactly and free. The trigger is then 80% of the window,
# but never closer to the top than the answer needs plus room for the turn to
# grow after it is measured - tool observations arrive AFTER the last request
# of a turn was counted. On a small window the second term is what binds.
CHAT_COMPACT_MARGIN = int(os.environ.get("CHAT_COMPACT_MARGIN", "4096"))
CHAT_COMPACT_TOKENS = int(os.environ.get(
    "CHAT_COMPACT_TOKENS",
    str(max(1024, min(int(CONTEXT_WINDOW * 0.80),
                      CONTEXT_WINDOW - MAX_TOKENS - CHAT_COMPACT_MARGIN)))))

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

# Recalling an episode reinforces it. The two terms of a stored salience have
# different shapes, and that asymmetry decides what a long-lived store ends up
# ordering by: the importance judgement is bounded by SALIENCE_IMPORTANCE_WEIGHT
# and is spent once, while reinforcement used to be additive and unbounded. Four
# recalls were worth the entire judgement, and in the evaluation corpus 77 of
# 1193 episodes ended pinned to the ceiling, where seven distinct importance
# values had become one number.
#
#   asymptotic (default)  s <- s + boost * (1 - s)
#       Each recall closes part of the remaining distance to 1.0, so a faded
#       episode gains much more from being needed again than an already strong
#       one does, the ordering the model produced is never overwritten, and the
#       ceiling is approached rather than hit.
#   additive              s <- min(1.0, s + boost)
#       The behaviour of the frozen corpus and of the published evaluation.
EPISODE_RECALL_BOOST = float(os.environ.get("EPISODE_RECALL_BOOST", "0.10"))
EPISODE_RECALL_RULE  = os.environ.get("EPISODE_RECALL_RULE", "asymptotic")

# What a recall was worth. The Curator says why it took each fragment; a
# fragment taken to see how something is written earns a fraction of what one
# taken for what it means earns. Measured over 799 recorded selections in the
# revision corpus, a quarter of all retrievals were purely procedural and drew
# the full increment - which is what let a routine episode reach the salience
# of a consequential one. 1.0 restores the old undifferentiated credit.
EPISODE_RECALL_PROCEDURAL_FACTOR = float(
    os.environ.get("EPISODE_RECALL_PROCEDURAL_FACTOR", "0.25"))

# How many already-stored episodes are shown to the Consolidator as a scale for
# its importance judgement. Asked in the abstract, the judgement collapses onto
# the bands the prompt names: across 1193 episodes of the revision corpus only
# 13 distinct values were ever used, 0.80 and 0.70 took 54% of the corpus
# between them, and one model family put 51% of everything on 0.80. Episodes
# that land on the same value are indistinguishable at formation, and it is
# then recall - not judgement - that orders them.
#
# Comparison is what a language model does well and an absolute scale is not,
# so the store supplies the scale: a few of its own past episodes, spread
# across whatever range it actually holds. 0 disables the block entirely and
# restores the absolute judgement of the published evaluation.
#
# The scale is the store's own past judgements, so it is a feedback loop: a
# memory that started out badly calibrated will keep confirming itself. The
# Consolidator is told the anchors are precedents rather than a rule, and is
# free to score below or above all of them, but nothing enforces that. Watch
# it on a long-lived store.
EPISODE_IMPORTANCE_ANCHORS = int(
    os.environ.get("EPISODE_IMPORTANCE_ANCHORS", "5"))

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
# How many of those slots are reserved for the most recent episodes, whatever
# they are about. Keywords answer questions about a SUBJECT; a question about a
# TIME - "what did we talk about yesterday" - shares no words with the episode
# that holds the answer, and would be met with the store's greatest hits.
# Reserved out of the pool, not added to it: the prompt does not grow.
CURATOR_CANDIDATES_RECENT    = int(os.environ.get("CURATOR_CANDIDATES_RECENT", "3"))

# ── Segmenting a batch run ──
# Whether a one-shot `pragma "task"` is JUDGED before it becomes an episode.
#
# A batch run has always written one, on the reasoning that the user asked for
# it and that settles the matter. It does not: "check whether the server is up"
# then becomes a memory with the same standing as a session where something was
# decided, and over months those records compete for the curator's candidate
# slots, age and go dormant like everything else, and - since a belief needs
# only two source episodes - repeated trivia can abstract into a rule.
#
# OFF BY DEFAULT, and the reason is not caution about the idea. The frozen
# evaluation corpus and the campaigns answering the reviewers both run through
# the batch path, and this changes HOW MANY episodes a run produces. That
# number appears in the published run inventory, so it has to change by an
# explicit act rather than as a side effect of pulling the repository. Set
# BATCH_SEGMENT=1 for ordinary use; leave it unset to reproduce a campaign.
BATCH_SEGMENT = (os.environ.get("BATCH_SEGMENT", "").strip().lower()
                 in ("1", "true", "yes", "on"))
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

# Whether the memory faculties constrain their JSON with a schema.
#
# Exists so the schema can be ablated on its own: the question "do
# constrained faculties change what memory holds?" needs everything else held
# constant. Set MEMORY_SCHEMA=0 for the unconstrained arm.
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
# file-mutating skills (write_file, append_file, insert_*,
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
