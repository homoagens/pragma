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

import os
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
# A command line handed to another shell as a string: `bash -c "rm -rf x"`,
# `eval '...'`, `cmd /c "..."`, `powershell -Command "..."`. Read as words it
# is only `bash`; the string is read as a command line of its own.
_SHELL_STRING = re.compile(
    r"(?:\b(?:ba|z|da|k|fi|c)?sh(?:\.exe)?(?:\s+-[a-z]+)*?\s+-[a-z]*c[a-z]*"
    r"|\beval|\bcmd(?:\.exe)?\s+/[ck]"
    r"|\b(?:powershell|pwsh)(?:\.exe)?(?:\s+-\w+)*?\s+-(?:c|command))"
    r"\s+(?:\"((?:[^\"\\]|\\.)*)\"|'([^']*)')", re.I)
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


def _segment(raw: str) -> str:
    """Why one command of a command line is held, or ""."""
    if re.match(r"^(sudo|doas)\b", raw):
        return "runs as administrator"
    words = _words(raw)
    if not words:
        return ""
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


# ── what the person allowed ───────────────────────────────────────────────────
#
# A project can list commands that need not wait: `rm build/*`, `git push`,
# `pip install -r requirements.txt`. A pattern is compared with ONE command of
# the line at a time, word by word, so it can never cover more than it says:
#
#   *      inside a word, any characters but `/` and spaces: `rm *.tmp` allows
#          `rm a.tmp`, not `rm sub/a.tmp` and not `rm a.tmp b.tmp`
#   **     inside a word, any characters but spaces, `/` included
#   ?      one character, not `/`
#   *      as the LAST word on its own, any further words: `git push *`
#
# Every held command of a line must be covered, each by some pattern, for the
# line to run without asking: `rm build/a ; rm -rf ~` is not let through by
# `rm build/*`.

def _word_pattern(word: str) -> re.Pattern:
    out, i = "", 0
    while i < len(word):
        if word.startswith("**", i):
            out, i = out + r"[^\s]*", i + 2
        elif word[i] == "*":
            out, i = out + r"[^/\s]*", i + 1
        elif word[i] == "?":
            out, i = out + r"[^/\s]", i + 1
        else:
            out, i = out + re.escape(word[i]), i + 1
    return re.compile(out + r"\Z")


def _spellings(word: str, where: str, root: str) -> list[str]:
    """The ways a pattern may name what this word of a command names.

    The agent is told to write every path absolute, and a person writes a
    pattern for their project as `rm build/*`. So a path in a command is also
    tried relative to the project's folder - only when it is inside it: a
    path that leaves the folder keeps the spelling it has, and a pattern has
    to say so to cover it.
    """
    if not root or not ("/" in word or "\\" in word or word.startswith(("~", "."))):
        return [word]
    # Not the word as written: `build/a.o` run from a subfolder is not the
    # project's build/. What it names is the full path, and the project-
    # relative one when there is one.
    full = os.path.normpath(os.path.join(where or root, os.path.expanduser(word)))
    out = [full]
    try:
        inside = os.path.relpath(full, os.path.normpath(root))
    except ValueError:                       # another drive, on Windows
        return out
    if inside != ".." and not inside.startswith(".." + os.sep):
        out.append(inside.replace(os.sep, "/"))
    return out


def covers(pattern: str, command: str, where: str = "", root: str = "") -> bool:
    """Does this allowed pattern cover this one command, word for word?

    `root` is the project's folder and `where` the folder the command runs in:
    see _spellings for what they change.
    """
    want = [w.strip("\"'") for w in (pattern or "").split()]
    have = [w.strip("\"'") for w in (command or "").split()]
    if not want:
        return False
    rest = want[-1] == "*"
    if rest:
        want = want[:-1]
        if len(have) < len(want):
            return False
        have = have[:len(want)]
    if len(have) != len(want):
        return False
    return all(any(_word_pattern(os.path.expanduser(p) if p.startswith("~") else p).match(s)
                   for s in _spellings(h, where, root))
               for p, h in zip(want, have))


def held(command: str, allowed=(), where: str = "", root: str = "") -> str:
    """Why this command must wait for the person, or "" when it need not.

    `allowed` are the patterns the project lets through without asking: a
    command line runs without the question only when every command in it that
    would be held is covered by one of them. `root` is the project's folder,
    `where` the folder the command runs in.
    """
    text = command or ""
    patterns = [p for p in (allowed or ()) if str(p).strip()]

    def free(part: str) -> bool:
        return any(covers(p, part, where, root) for p in patterns)

    if _PIPED_SCRIPT.search(text) and not free(text):
        return "runs a script downloaded from the internet"
    # Before the command is cut at its semicolons and brackets, which would
    # cut a `python -c "import shutil; shutil.rmtree(...)"` in two.
    if _PYTHON.search(text) and _PYTHON_DELETES.search(text) and not free(text):
        return "deletes files"
    for m in _SHELL_STRING.finditer(text):
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        why = held(inner.replace('\\"', '"'), allowed, where, root)
        if why:
            return why
    for segment in _SEGMENTS.split(text):
        raw = segment.strip()
        if not raw:
            continue
        why = _segment(raw)
        if why and not free(raw):
            return why
    return ""


def held_in(text: str) -> str:
    """Why a command written somewhere in this prose would be held, or "".

    For a sentence that carries a command rather than a command line - a
    suggestion, a review's next step. It is tried from every word on, since
    "Run rm tetris.py to finish" and "now run rm build/*.o for me" do not
    open with the command.
    """
    words = (text or "").split()
    for i in range(len(words)):
        why = held(" ".join(words[i:]))
        if why:
            return why
    return ""
