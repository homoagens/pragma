#!/usr/bin/env bash
# start.sh - the terminal harness.
#
# The project launcher - the briefing, the registry, switching between
# memories - is a PowerShell module, so on Linux and macOS this opens the
# conversation directly against the store in PRAGMA_DATA_DIR (~/.pragma by
# default) and the workspace you are standing in. Everything the conversation
# itself offers is here: the slash commands, the memory, consolidation on the
# way out.
#
# The browser interface has moved to pragma-gui.sh.
cd "$(dirname "$0")" || exit 1
exec ./venv/bin/python -m agent.chat --memory "$@"
