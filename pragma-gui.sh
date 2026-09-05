#!/usr/bin/env bash
# pragma-gui.sh - the browser interface.
#
# Pragma's default is the terminal harness (start.sh). This launches the web
# UI instead, which is the older way in and still the one to use when you want
# the thread list and the panes.
#
# agent.run opens the browser itself; no extra open here.
cd "$(dirname "$0")" || exit 1
./venv/bin/python -m agent.run "$@"
