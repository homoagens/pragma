#!/bin/bash
# =============================================================================
# configure.sh — interactive setup of Pragma's .env (Linux / macOS).
#
# Pipeline: install -> configure -> start.
# Writes the OpenAI-compatible LLM endpoint settings into .env. Any existing
# .env is backed up first, and current values are offered as defaults so
# nothing already configured is overwritten unless you change it.
# =============================================================================

set -e
cd "$(dirname "$0")"

ENV_FILE=".env"

# Read the current value of a KEY from .env (empty if unset).
current() {
    [ -f "$ENV_FILE" ] && grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true
}

# Prompt with a default; empty input keeps the default.
ask() {
    local prompt="$1" def="$2" reply
    if [ -n "$def" ]; then
        read -r -p "$prompt [$def]: " reply
        echo "${reply:-$def}"
    else
        read -r -p "$prompt: " reply
        echo "$reply"
    fi
}

echo "Pragma configuration"
echo "Pragma talks to ONE OpenAI-compatible endpoint: POST {URL}/chat/completions"
echo "The base URL must end in /v1. Examples:"
echo "  llama.cpp http://127.0.0.1:8080/v1   LM Studio http://127.0.0.1:1234/v1"
echo "  Ollama    http://127.0.0.1:11434/v1  vLLM      http://127.0.0.1:8000/v1"
echo

cur_url=$(current LLM_BASE_URL);   [ -z "$cur_url" ] && cur_url="http://127.0.0.1:8080/v1"
cur_model=$(current DEFAULT_MODEL)
cur_key=$(current LLM_API_KEY)

LLM_BASE_URL=$(ask "Backend URL (ends in /v1)" "$cur_url")
DEFAULT_MODEL=$(ask "Model name (as the server reports it)" "$cur_model")
LLM_API_KEY=$(ask "API key (leave empty for local servers)" "$cur_key")

# Back up an existing .env before changing it.
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.bak"
    echo "Backed up existing .env -> .env.bak"
fi

# Upsert the three keys, preserving every other line already in .env.
tmp=$(mktemp)
if [ -f "$ENV_FILE" ]; then
    grep -vE "^(LLM_BASE_URL|DEFAULT_MODEL|LLM_API_KEY)=" "$ENV_FILE" > "$tmp" || true
fi
{
    echo "LLM_BASE_URL=$LLM_BASE_URL"
    echo "DEFAULT_MODEL=$DEFAULT_MODEL"
    echo "LLM_API_KEY=$LLM_API_KEY"
} >> "$tmp"
mv "$tmp" "$ENV_FILE"
echo "Wrote $ENV_FILE"

# Health check: GET {URL}/models.
echo
echo "Checking $LLM_BASE_URL/models ..."
if command -v curl >/dev/null 2>&1; then
    auth=()
    [ -n "$LLM_API_KEY" ] && auth=(-H "Authorization: Bearer $LLM_API_KEY")
    code=$(curl -s -o /dev/null -w "%{http_code}" "${auth[@]}" "$LLM_BASE_URL/models" || echo "000")
    if [ "$code" = "200" ]; then
        echo "OK — endpoint reachable. Run ./start.sh to launch Pragma."
    else
        echo "WARNING — endpoint returned HTTP $code. Is the server running?"
        echo "You can still launch Pragma and fix this later (Settings in the UI)."
    fi
else
    echo "(curl not found — skipping health check.)"
fi
