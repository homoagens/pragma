#!/bin/bash
# =============================================================================
# configure.sh - interactive setup of Pragma's .env (Linux / macOS).
#
# Pipeline: install -> configure -> start.
# Thin wrapper: all logic lives in configure.py (robust, cross-platform).
# Prefers the repo venv's Python so `requests` is available for the health
# check.
# =============================================================================

cd "$(dirname "$0")"

PY="python3"
[ -x "venv/bin/python" ] && PY="venv/bin/python"

exec "$PY" configure.py
