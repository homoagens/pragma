#!/bin/sh
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.
#
# install.sh - the Python environment, then `pragma` in every shell.
#
#     ./install.sh                environment + a line in your shell profile
#     ./install.sh --no-profile   environment only, leave the profile alone
#     ./install.sh --uninstall    remove the profile line (keeps venv and data)
#     ./install.sh --python <exe> build the venv with that interpreter
#
# The mirror of install.ps1 on Linux and macOS. The profile line is written
# between markers and replaced in place on a re-run, so installing twice, or
# after moving the repository, updates the path instead of leaving a second
# stale line behind.
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
BEGIN="# >>> pragma >>>"
END="# <<< pragma <<<"
PYTHON=""
NO_PROFILE=0
UNINSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --no-profile) NO_PROFILE=1 ;;
        --uninstall)  UNINSTALL=1 ;;
        --python)     PYTHON="$2"; shift ;;
        -h|--help)    sed -n '5,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

step() { printf '  %s\n' "$1"; }
done_() { printf '  \033[32m%s\033[0m\n' "$1"; }
warn() { printf '  \033[33m%s\033[0m\n' "$1"; }

# The profile file: the one the login shell actually reads. bash reads
# ~/.bashrc in an interactive shell, zsh ~/.zshrc; anything else gets
# ~/.profile, which every POSIX shell reads.
profile_file() {
    case "$(basename "${SHELL:-/bin/sh}")" in
        bash) [ "$(uname -s)" = "Darwin" ] && echo "$HOME/.bash_profile" || echo "$HOME/.bashrc" ;;
        zsh)  echo "${ZDOTDIR:-$HOME}/.zshrc" ;;
        fish) echo "$HOME/.config/fish/config.fish" ;;
        *)    echo "$HOME/.profile" ;;
    esac
}

strip_block() {                         # remove an existing pragma block
    file="$1"
    [ -f "$file" ] || return 0
    awk -v b="$BEGIN" -v e="$END" '
        $0 == b {skip = 1} skip == 0 {print} $0 == e {skip = 0}' "$file" > "$file.pragma-tmp"
    mv "$file.pragma-tmp" "$file"
}

PROFILE=$(profile_file)

if [ "$UNINSTALL" = "1" ]; then
    strip_block "$PROFILE"
    done_ "removed the pragma line from $PROFILE"
    step "the environment and everything under ~/.pragma are untouched."
    exit 0
fi

printf '\n  Pragma\n\n'

# --- the interpreter ----------------------------------------------------------
if [ -z "$PYTHON" ]; then
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then PYTHON=$(command -v "$candidate"); break; fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "  no python found. Install Python 3.10 or newer and run this again." >&2
    exit 1
fi
version=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$version" in
    3.10|3.11|3.12|3.13|3.14|3.15) ;;
    *) echo "  $PYTHON is Python $version; Pragma needs 3.10 or newer." >&2; exit 1 ;;
esac
step "python     $PYTHON ($version)"

# --- the environment ----------------------------------------------------------
if [ ! -x "$ROOT/venv/bin/python" ]; then
    step "building the environment in venv/ ..."
    if ! "$PYTHON" -m venv "$ROOT/venv" 2>/dev/null; then
        # Debian and Ubuntu ship venv without ensurepip in a separate package.
        warn "python -m venv failed - on Debian or Ubuntu:"
        warn "    sudo apt install python3-venv"
        exit 1
    fi
fi
step "installing what it needs ..."
"$ROOT/venv/bin/python" -m pip install --quiet --upgrade pip >/dev/null
"$ROOT/venv/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"
chmod +x "$ROOT/pragma"
done_ "the environment is ready"

# --- `pragma`, in every shell -------------------------------------------------
if [ "$NO_PROFILE" = "1" ]; then
    step "profile left alone. Run it from here with ./pragma"
    exit 0
fi
strip_block "$PROFILE"
mkdir -p "$(dirname "$PROFILE")"
if [ "$(basename "$PROFILE")" = "config.fish" ]; then
    line="alias pragma \"$ROOT/pragma\""
else
    line="alias pragma='$ROOT/pragma'"
fi
{ printf '%s\n' "$BEGIN"; printf '%s\n' "$line"; printf '%s\n' "$END"; } >> "$PROFILE"
done_ "added pragma to $PROFILE"
printf '\n  Open a new terminal - this one has not read your profile yet - and type:\n\n'
printf '      pragma\n\n'
