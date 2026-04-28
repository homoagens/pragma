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

MAX_TOKENS     = 4096
TIMEOUT        = 300   # seconds — increase for slow or large-context models

# Maximum number of ReAct loop steps before a forced verdict is requested.
MAX_STEPS = int(os.environ.get("MAX_STEPS", "15"))

# Model context window (tokens). Compression thresholds are derived from this.
CONTEXT_WINDOW = 65536

# Memory compression thresholds (see memory.py).
# Compression triggers when EITHER threshold is exceeded:
#   - MAX_MESSAGES: total messages in the list
#   - MAX_CHARS:    total characters (token proxy; 1 token ≈ 4 chars)
MAX_MESSAGES     = 30
MAX_CHARS        = int(CONTEXT_WINDOW * 4 * 0.55)  # ~143k chars ≈ 36k tokens
MESSAGES_RECENT  = 6       # recent messages always preserved during compression

# Character budget for conversation history carried across requests.
# 15% of context window — enough for 4-6 detailed exchanges.
HISTORY_MAX_CHARS = int(CONTEXT_WINDOW * 4 * 0.15)  # ~39k chars

# ─────────────────────────────────────────────
# INTERNAL (not needed for standard providers)
# ─────────────────────────────────────────────
BACKEND_URL = os.environ.get("BACKEND_URL", "")
BACKEND_KEY = os.environ.get("BACKEND_KEY", "")
