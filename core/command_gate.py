# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""Which shell commands cannot be undone.

The file tools copy a file before they change it, so `revert` can put it
back; a command run through the shell passes no such point. Most commands do
nothing that matters for that - they read, build, test - but some destroy
what `revert` cannot restore, or reach beyond the workspace: deleting files,
discarding or pushing git history, installing software, running as root.

A rule in the prompt asks the agent not to do those on a guess, and the
critic is told the same. Neither is a guarantee: a model reading "do the
action items" can take it for permission, and did. So in a conversation the
command itself is held until the person allows it - see agent/chat.py - and
this module is what decides which commands are held.

It reads the command as text, segment by segment, and answers with the
reason a command is held, or "". It errs towards asking: a command that only
mentions `rm` inside a string is held too, and costs one question. What it
does not see is a command that destroys without saying so - a script that
deletes when run, an output redirected over an existing file. Those are why
the rule in the prompt stays.
"""

from __future__ import annotations

import re

# Where one command ends and the next begins.
_SEGMENTS = re.compile(r"\|\||&&|[;|&\n`]|\$\(|\(")

# Words that run the word after them.
_PREFIXES = {"sudo", "doas", "nohup", "time", "command", "builtin", "exec",
             "xargs", "env", "nice", "timeout", "watch"}

_DELETE = {"rm", "rmdir", "unlink", "shred", "srm", "trash", "trash-put",
           "del", "erase", "rd", "remove-item", "ri"}
_DISK = {"dd", "wipefs", "fdisk", "parted"}
_PACKAGE_MANAGERS = {"pip", "pip3", "npm", "pnpm", "yarn", "bun", "apt", "apt-get",
                     "dnf", "yum", "zypper", "pacman", "brew", "snap", "conda",
                     "mamba", "cargo", "gem", "go", "choco", "winget", "scoop"}
_INSTALLING = {"install", "i", "add", "ci", "uninstall", "remove", "rm", "purge",
               "-s", "-r", "-syu"}

_PIPED_SCRIPT = re.compile(r"\b(curl|wget|iwr|invoke-webrequest)\b[^|]*\|\s*(sudo\s+)?"
                           r"(ba|z|da|k|fi)?sh\b|\|\s*(iex|invoke-expression)\b", re.I)
_PYTHON = re.compile(r"(^|[\s;&|(/\\])(python[\d.]*|py)(\.exe)?\s", re.I)
_PYTHON_DELETES = re.compile(r"\b(shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir|"
                             r"os\.removedirs|send2trash)\b|\.unlink\(|\.rmdir\(")


def _words(segment: str) -> list[str]:
    """The words of one command, quotes taken off, the runners in front of it
    dropped: `sudo env X=1 rm -rf a` is about `rm`."""
    words = [w.strip("\"'") for w in segment.split()]
    while words:
        head = words[0].rsplit("/", 1)[-1].lower()
        if head in _PREFIXES:
            words = words[1:]
            # The options and settings of the runner, up to the command it runs.
            while words and (words[0].startswith("-") or re.match(r"^\w+=", words[0])
                             or (head in ("timeout", "nice", "watch") and re.match(r"^[\d.]+[smhd]?$", words[0]))):
                words = words[1:]
            continue
        if re.match(r"^\w+=", words[0]):            # FOO=bar cmd
            words = words[1:]
            continue
        break
    return words


def _git(args: list[str]) -> str:
    """The reason a git command is held, or ""."""
    i = 0
    while i < len(args) and args[i].startswith("-"):     # git -C path ..., git --no-pager ...
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(args):
        return ""
    sub, rest = args[i].lower(), [a.lower() for a in args[i + 1:]]
    if sub == "push":
        return "sends commits to another repository"
    if sub == "reset" and "--hard" in rest:
        return "throws away uncommitted changes"
    if sub == "clean" and any(a.startswith("-") and "f" in a for a in rest):
        return "deletes untracked files"
    if sub == "checkout" and ("--" in rest or "." in rest or "-f" in rest or "--force" in rest):
        return "throws away uncommitted changes"
    if sub == "restore" and [a for a in rest if a not in ("--staged", "-s", "--quiet")]:
        if "--staged" not in rest or "--worktree" in rest or "-w" in rest:
            return "throws away uncommitted changes"
    if sub == "branch" and ("-d" in rest and "-f" in rest or "-D" in args[i + 1:]
                            or "--delete" in rest and "--force" in rest):
        return "deletes a branch"
    if sub == "stash" and rest[:1] in (["drop"], ["clear"]):
        return "throws away stashed changes"
    if sub == "rm":
        return "deletes files"
    if sub == "filter-branch" or sub == "filter-repo":
        return "rewrites the history"
    return ""


def held(command: str) -> str:
    """Why this command must wait for the person, or "" when it need not."""
    text = command or ""
    if _PIPED_SCRIPT.search(text):
        return "runs a script downloaded from the internet"
    # Before the command is cut at its semicolons and brackets, which would
    # cut a `python -c "import shutil; shutil.rmtree(...)"` in two.
    if _PYTHON.search(text) and _PYTHON_DELETES.search(text):
        return "deletes files"
    for segment in _SEGMENTS.split(text):
        raw = segment.strip()
        if not raw:
            continue
        if re.match(r"^(sudo|doas)\b", raw):
            return "runs as administrator"
        words = _words(raw)
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if head.endswith(".exe"):
            head = head[:-4]
        args = words[1:]
        low = [a.lower() for a in args]
        if head in _DELETE:
            return "deletes files"
        if head in _DISK or head.startswith("mkfs"):
            return "writes over a disk"
        if head == "find" and ("-delete" in low or any(
                a in ("-exec", "-execdir", "-ok") and i + 1 < len(low)
                and low[i + 1].rsplit("/", 1)[-1] in _DELETE for i, a in enumerate(low))):
            return "deletes files"
        if head == "git":
            why = _git(args)
            if why:
                return why
        if head in _PACKAGE_MANAGERS and low and low[0] in _INSTALLING:
            return "installs or removes software"
        if re.match(r"^python[\d.]*$|^py$", head):
            if len(low) >= 3 and low[0] == "-m" and low[1] in ("pip", "pip3") and low[2] in _INSTALLING:
                return "installs or removes software"
        if head == "uv" and low[:2] in (["pip", "install"], ["pip", "uninstall"], ["tool", "install"]) \
                or head == "uv" and low[:1] in (["add"], ["remove"]):
            return "installs or removes software"
    return ""
