#!/usr/bin/env bash
# =============================================================================
# build.sh - builds dist/pragma from the current Pragma source (Linux / macOS).
#
# Run this every time you change Pragma and want a fresh executable.
# It cleans previous artifacts, ensures PyInstaller is installed, and
# rebuilds using pragma.spec.
#
# NOTE: PyInstaller does NOT cross-compile. Run this ON the OS you want the
# executable for: Linux build on Linux, macOS build on macOS.
#
# IMPORTANT: must run in a Python environment that has ALL of Pragma's
# dependencies installed. The script auto-uses the repo venv if present.
# =============================================================================

set -e
cd "$(dirname "$0")"

# --- pick the interpreter: prefer the repo venv ------------------------------
PY="python3"
[ -x "venv/bin/python" ]  && PY="venv/bin/python"
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"
echo "[pragma-build] using interpreter: $PY"

# --- clean previous build ----------------------------------------------------
echo "[pragma-build] cleaning build/ and dist/ ..."
rm -rf build dist

# --- ensure PyInstaller is available -----------------------------------------
echo "[pragma-build] checking PyInstaller ..."
"$PY" -m pip install --quiet --upgrade pyinstaller

# --- build -------------------------------------------------------------------
echo "[pragma-build] running PyInstaller ..."
"$PY" -m PyInstaller --noconfirm --clean pragma.spec

echo
echo "[pragma-build] DONE  ->  dist/pragma"
echo "[pragma-build] test it with:  ./dist/pragma --port 8006"
