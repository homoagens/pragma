#!/bin/bash
cd "$(dirname "$0")"
# agent.run opens the browser itself (works for the exe too); no extra open here.
./venv/bin/python -m agent.run
