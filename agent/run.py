# agent/run.py — CLI entry point for Pragma
#
# Usage:
#   python -m agent.run                     # port 8006, current cwd
#   python -m agent.run --port 8080
#   python -m agent.run --workdir /my/project

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


def main():
    parser = argparse.ArgumentParser(
        description="Pragma — autonomous coding agent"
    )
    parser.add_argument("--port",    type=int, default=8006,
                        help="HTTP port (default: 8006)")
    parser.add_argument("--host",    default="127.0.0.1",
                        help="host (default: 127.0.0.1)")
    parser.add_argument("--workdir", default=None,
                        help="working directory (default: current directory)")
    parser.add_argument("--reload",  action="store_true",
                        help="auto-reload on file changes (dev mode)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open the web UI in a browser on startup")
    args = parser.parse_args()

    if args.workdir:
        target = Path(args.workdir).resolve()
        if not target.is_dir():
            print(f"ERROR: workdir not found: {target}")
            sys.exit(1)
        os.chdir(target)

    cwd = os.getcwd()
    url = f"http://{args.host}:{args.port}/"
    print("Pragma")
    print(f"  workdir : {cwd}")
    print(f"  server  : http://{args.host}:{args.port}")
    print(f"  UI      : {url}")
    print()

    # Open the web UI in the default browser shortly after startup.
    # A short delay lets uvicorn bind the port first. Skipped in --reload
    # (dev mode) and when --no-browser is passed.
    if not args.no_browser and not args.reload:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(
        "agent.server:app",
        host    = args.host,
        port    = args.port,
        reload  = args.reload,
    )


if __name__ == "__main__":
    main()
