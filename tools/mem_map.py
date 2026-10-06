# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.
#
# mem_map.py — inspect a Pragma memory store.
#
# Usage:
#   python tools\mem_map.py [store_dir]            -> memory map (default)
#   python tools\mem_map.py [store_dir] --beliefs  -> semantic beliefs
#   python tools\mem_map.py [store_dir] --diff     -> before/after of every
#                                                               reinterpretation/reformulation
#   python tools\mem_map.py [store_dir] --oblio    -> dormant zone only
#   python tools\mem_map.py [store_dir] --last     -> the newest episode, in full
#   python tools\mem_map.py [store_dir] --sweep    -> MUTATES: run the real
#                                                               forgetting sweep now (moves
#                                                               below-threshold episodes to
#                                                               dormant/), instead of waiting
#                                                               for the next consolidation
#   python tools\mem_map.py [store_dir] --clock-set-> MUTATES: settle the story
#                                                               clock: bank the real time
#                                                               elapsed at the PREVIOUS pace,
#                                                               then record the current pace
#   python tools\mem_map.py [store_dir] --jump N   -> MUTATES: the time machine's
#                                                               core. Ages every episode by N
#                                                               simulated months (timestamps
#                                                               shifted back by N * half_life
#                                                               days), sweeps, updates the
#                                                               story clock. The half-life is
#                                                               NEVER changed: after a jump,
#                                                               physical time = story time
#                                                               again at the configured pace.
#
# store_dir defaults to $PRAGMA_DATA_DIR, then ~/.pragma. Honors
# $EPISODE_DECAY_HALF_LIFE_DAYS and $EPISODE_DORMANT_THRESHOLD so the effective
# salience matches whatever time-acceleration you set.
#
# All subcommands are read-only EXCEPT --sweep, --clock-set and --jump.
# --sweep calls the production core/episodes.py sweep() — the same maintenance
# that normally runs only as a side effect of consolidating a session.
#
# THE JUMP (how the time machine works without touching the pace). Decay reads
#   eff = salience * 0.5^((now - last_recalled) / half_life)
# so making a memory "N months older" does not require running a fast clock:
# shifting its timestamps back by N * half_life days bakes exactly N
# half-lives of extra decay into the stored state, permanently, while the
# session keeps its normal pace (convention: 1 half-life = 1 month, matching
# the 30-day default). This is what --jump does, then it sweeps (so episodes
# that fell below the dormancy threshold genuinely move to dormant/) and
# advances the story clock by N months.
#
# THE STORY CLOCK. story_clock.json accumulates simulated months: jumps add
# their months directly; between jumps the clock accrues real elapsed time at
# the pace recorded in the ledger. The map view only READS the ledger.

import datetime as D
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_args = sys.argv[1:]
_jump_months = None
if "--jump" in _args:
    _ji = _args.index("--jump")
    if _ji + 1 >= len(_args):
        print("Usage: mem_map.py [store_dir] --jump <months>")
        sys.exit(2)
    try:
        _jump_months = float(_args[_ji + 1])
    except ValueError:
        print(f"--jump: '{_args[_ji + 1]}' is not a number")
        sys.exit(2)
    _args = _args[:_ji] + _args[_ji + 2:]   # consume the value token too
_flags = {a for a in _args if a.startswith("--")}
if _jump_months is not None:
    _flags.add("--jump")
_rest = [a for a in _args if not a.startswith("--")]

d = _rest[0] if _rest else os.environ.get(
    "PRAGMA_DATA_DIR", os.path.expanduser("~/.pragma"))
hl = float(os.environ.get("EPISODE_DECAY_HALF_LIFE_DAYS", "30"))
thr = float(os.environ.get("EPISODE_DORMANT_THRESHOLD", "0.15"))
now = D.datetime.now(D.timezone.utc)


def age_days(e):
    t = e.get("last_recalled") or e.get("ts") or ""
    try:
        ref = D.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=D.timezone.utc)
        return max(0.0, (now - ref).total_seconds() / 86400)
    except Exception:
        return 0.0


def eff(e):
    return e["salience"] * (0.5 ** (age_days(e) / hl)) if hl > 0 else e["salience"]


def load(sub):
    pat = os.path.join(d, "episodes", sub, "ep_*.json") if sub \
        else os.path.join(d, "episodes", "ep_*.json")
    out = []
    for f in sorted(glob.glob(pat)):
        try:
            out.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass
    return out


def learnings():
    try:
        return json.load(open(os.path.join(d, "learnings.json"),
                              encoding="utf-8")).get("entries", [])
    except Exception:
        return []


# ── story clock ──────────────────────────────────────────────────────────────

CLOCK_PATH = os.path.join(d, "story_clock.json")
ISO = "%Y-%m-%dT%H:%M:%SZ"


def clock_read():
    try:
        return json.load(open(CLOCK_PATH, encoding="utf-8"))
    except Exception:
        return None


def clock_pending_months(c):
    """Months accrued since the last settle, at the pace stored in the ledger
    (NOT the current env pace — the env only becomes truth after --clock-set)."""
    try:
        ref = D.datetime.strptime(c["ts"], ISO).replace(tzinfo=D.timezone.utc)
        pace = float(c.get("half_life_days") or 30.0)
        if pace <= 0:
            return 0.0
        return max(0.0, (now - ref).total_seconds() / 86400.0) / pace
    except Exception:
        return 0.0


def fmt_story(months):
    whole = int(months)
    years, mo = divmod(whole, 12)
    days = int(round((months - whole) * 30.44))
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if mo:
        parts.append(f"{mo} month{'s' if mo != 1 else ''}")
    parts.append(f"{days} day{'s' if days != 1 else ''}")
    return ", ".join(parts)


def clock_line():
    c = clock_read()
    if c is None:
        return "story time: (clock not started - run pragma -Time once)"
    total = float(c.get("months", 0.0)) + clock_pending_months(c)
    started = (c.get("started") or "?")[:10]
    return f"story time: {fmt_story(total)} elapsed since {started}"


def clock_set():
    """The settle: bank elapsed-at-previous-pace, then record the current
    env pace as the one in effect from now on."""
    os.makedirs(d, exist_ok=True)
    c = clock_read()
    now_s = now.strftime(ISO)
    if c is None:
        c = {"months": 0.0, "ts": now_s, "half_life_days": hl, "started": now_s}
    else:
        c["months"] = float(c.get("months", 0.0)) + clock_pending_months(c)
        c["ts"] = now_s
        c["half_life_days"] = hl
    with open(CLOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
    print(clock_line() + f"   (pace now: {hl} d/half-life)")


# ── drawing ──────────────────────────────────────────────────────────────────
# These views are what /memory shows inside a conversation, so they are drawn
# for a person rather than for a log: a title, the same two-space gutter as the
# rest of the interface, labels in grey, and long text wrapped under itself
# instead of running off the edge and carrying on at column 0. What the numbers
# mean is said in words once, under the view, rather than as column headings
# ("raw", "eff", "reint") that only the code could read.

import shutil as _shutil
import textwrap as _tw

_TTY = sys.stdout.isatty()


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _TTY else str(text)


def _grey(text):
    return _c("38;5;242", text)


def _accent(text):
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        raw = "178;132;255"
    return _c("38;2;" + raw, text)


def _width():
    try:
        return max(40, _shutil.get_terminal_size((100, 24)).columns - 1)
    except Exception:
        return 99


def _dot():
    try:
        "·".encode(sys.stdout.encoding or "ascii")
        return " · "
    except Exception:
        return " - "


def _n(count, one, many=""):
    count = int(count or 0)
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _title(name, right=""):
    print()
    print("  " + _accent(name) + ("   " + _grey(right) if right else ""))
    print()


def _wrap(text, lead, width=None, paint=None):
    """`text` under a first line starting with `lead`, the rest aligned under it.

    Wrapped as plain text and painted line by line afterwards: colour codes
    inside the text would count as width and be split across lines.
    """
    width = width or _width()
    pad = " " * _visible(lead)
    parts = _tw.wrap(" ".join(str(text or "").split()), max(20, width - len(pad)),
                     break_on_hyphens=False) or [""]
    paint = paint or (lambda x: x)
    print(lead + paint(parts[0]))
    for part in parts[1:]:
        print(pad + paint(part))


def _visible(text):
    import re as _re
    return len(_re.sub(r"\x1b\[[0-9;]*m", "", text))


def _field(label, text, width=None):
    _wrap(text, "  " + _grey(f"{label:<15}"), width)


def _say(text):
    """A closing sentence in grey, wrapped."""
    width = _width()
    for part in _tw.wrap(" ".join(text.split()), max(20, width - 2)) or [""]:
        print("  " + _grey(part))


def _bar(value, cells=8):
    """A strength from 0 to 1 as a short bar, where the console can draw one."""
    try:
        "▮▯".encode(sys.stdout.encoding or "ascii")
        full, empty = "▮", "▯"
    except Exception:
        full, empty = "#", "."
    value = max(0.0, min(1.0, float(value or 0)))
    k = int(round(value * cells))
    return full * k + empty * (cells - k)


def _when(stamp):
    try:
        t = D.datetime.strptime(stamp, ISO).replace(tzinfo=D.timezone.utc)
    except Exception:
        return str(stamp or "")
    return t.astimezone().strftime("%d %b %Y, %H:%M")


def show_map():
    active, dormant = load(""), load("dormant")
    _title("what is remembered",
           f"{_n(len(active), 'episode')} active{_dot()}{len(dormant)} dormant")
    if not active and not dormant:
        _say("Nothing yet. What is said in a conversation is written to memory when the "
             "project closes (ctrl+D), or when the conversation grows too long to keep "
             "in view.")
        print()
        return
    width = _width()
    for e in sorted(active, key=eff, reverse=True):
        r = len(e.get("interpretation_history") or [])
        lead = f"    {_accent(_bar(eff(e)))} {eff(e):.2f}  "
        text = e.get("goal", "") or "(no goal recorded)"
        if r:
            text += f"   (meaning revised {_n(r, 'time')})"
        _wrap(text, lead, width)
    if dormant:
        print()
        print("  " + _grey(f"dormant - {_n(len(dormant), 'episode')} below {thr:g}, out of recall"))
        for e in sorted(dormant, key=eff, reverse=True)[:5]:
            _wrap(e.get("goal", ""), "    " + _grey(f"{_bar(eff(e))} {eff(e):.2f}  "), width, _grey)
        if len(dormant) > 5:
            print("    " + _grey(f"and {len(dormant) - 5} more - /memory dormant"))
    print()
    story = clock_read()
    _say(f"Strength is how readily a memory comes back. It halves every {hl:g} days "
         f"unless the memory is recalled, and below {thr:g} the memory goes dormant."
         + (f" {clock_line()}." if story is not None else ""))
    print()


def show_beliefs():
    ents = learnings()
    live = [e for e in ents if e.get("status", "active") == "active"]
    _title("what it has concluded",
           f"{_n(len(live), 'belief')}" + (f"{_dot()}{len(ents) - len(live)} retired"
                                           if len(ents) != len(live) else ""))
    if not ents:
        _say("No beliefs yet. A belief is drawn when two or more episodes point the same "
             "way, so they appear after a few sessions, not after the first.")
        print()
        return
    width = _width()
    for e in sorted(ents, key=lambda x: (x.get("status", "active") != "active",
                                         -float(x.get("confidence", 0) or 0))):
        retired = e.get("status", "active") != "active"
        text = e.get("text", "")
        _wrap(text, "  " + (_grey("-") if retired else _accent("●")) + " ", width,
              _grey if retired else None)
        facts = [f"confidence {float(e.get('confidence', 0) or 0):.2f}",
                 f"confirmed {e.get('confirmations', 0)}",
                 f"contradicted {e.get('contradictions', 0)}"]
        if e.get("reformulations"):
            facts.append(f"rewritten {_n(e['reformulations'], 'time')}")
        if retired:
            facts.append(str(e.get("status")))
        print("    " + _grey(_dot().join(facts)))
        for h in (e.get("text_history") or [])[-2:]:
            _wrap(f"was: {h.get('text', '')}", "    ", width, _grey)
        print()


def show_sizes():
    """How wordy the store has become, against what actually reaches a prompt.

    Two different worries, and only one of them is bounded by the code. What
    the curator injects is capped hard - at most CURATOR_MAX_FRAGMENTS
    fragments, each with its narrative clipped to 400 chars and its meaning
    to 200 - so a prolix store cannot flood a prompt through that path. What
    is NOT capped is a belief's text, and nothing caps how unreadable the
    stored JSON itself becomes. This view watches both.
    """
    import statistics as st

    eps = load("") + load("dormant")
    ents = learnings()
    _title("how much of it can reach a prompt",
           f"{_n(len(eps), 'episode')}{_dot()}{_n(len(ents), 'belief')}")
    if not eps:
        _say("Nothing to measure yet: the memory is empty.")
        print()
        return

    def stats(vals):
        vals = [v for v in vals if v]
        if not vals:
            return None
        return int(st.median(vals)), max(vals)

    rows = [
        ("goal",           [len(e.get("goal", "") or "") for e in eps],           None),
        ("narrative",      [len(e.get("narrative", "") or "") for e in eps],      400),
        ("meaning",        [len(e.get("interpretation", "") or "") for e in eps], 200),
        ("belief",         [len(e.get("text", "") or "") for e in ents],          None),
    ]
    print("  " + _grey(f"{'':<14}{'typical':>9}{'longest':>9}   reaches the prompt"))
    for label, vals, cap in rows:
        s = stats(vals)
        if not s:
            continue
        med, mx = s
        if cap is None:
            note = "in full"
        elif mx <= cap:
            note = f"in full (up to {cap})"
        else:
            note = _c("33", f"cut at {cap}")
        print(f"  {label:<14}{med:>9}{mx:>9}   {note}")
    sizes = []
    for sub in ("", "dormant"):
        pat = os.path.join(d, "episodes", sub, "ep_*.json") if sub \
            else os.path.join(d, "episodes", "ep_*.json")
        sizes += [os.path.getsize(f) for f in glob.glob(pat)]
    if sizes:
        print("  " + _grey(f"{'on disk':<14}{int(st.median(sizes)):>9}{max(sizes):>9}   bytes per episode"))
    print()
    cap = 6
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "core"))
        import config as _cfg
        cap = getattr(_cfg, "CURATOR_MAX_FRAGMENTS", 6)
    except Exception:
        pass
    _say(f"Characters, not tokens. Recall brings at most {cap} fragments of about 600 "
         f"characters each into a turn - about {cap * 600 // 1000} KB, however big the "
         f"memory grows. Beliefs are not cut.")
    if ents:
        longest = max(len(e.get("text", "") or "") for e in ents)
        if longest > 300:
            print()
            _say(f"One belief is {longest} characters long, and beliefs reach the prompt whole.")
    print()


def show_diff():
    width = _width()
    items = []
    for e in load("") + load("dormant"):
        if e.get("interpretation_history"):
            items.append(("episode", e))
    for e in learnings():
        if e.get("text_history"):
            items.append(("belief", e))
    _title("meanings it has revised", _n(len(items), "revision") if items else "")
    if not items:
        _say("Nothing revised yet. An episode's meaning is revised when a later session "
             "sheds new light on it; a belief is rewritten when episodes contradict it.")
        print()
        return
    for kind, e in items:
        if kind == "episode":
            _wrap(e.get("goal", ""), "  " + _accent("episode") + "  ", width)
            for v in e.get("interpretation_history") or []:
                _wrap(v.get("text", ""), "    " + _grey(f"{'before':<8}"), width, _grey)
            _wrap(e.get("interpretation", ""), "    " + _grey(f"{'now':<8}"), width)
        else:
            _wrap(f"rewritten {_n(e.get('reformulations', 0), 'time')}",
                  "  " + _accent("belief") + "   ", width)
            for v in e.get("text_history") or []:
                _wrap(v.get("text", ""), "    " + _grey(f"{'before':<8}"), width, _grey)
            _wrap(e.get("text", ""), "    " + _grey(f"{'now':<8}"), width)
        print()


def show_oblio():
    dorm = load("dormant")
    _title("what has faded", _n(len(dorm), "episode") + " dormant" if dorm else "")
    if not dorm:
        _say(f"Nothing has faded. An episode goes dormant when its strength falls below "
             f"{thr:g}: it leaves recall, but it is not deleted.")
        print()
        return
    width = _width()
    for e in sorted(dorm, key=eff, reverse=True):
        since = e.get("dormant_since", "")
        _wrap(e.get("goal", "") + (f"   (since {_when(since)})" if since else ""),
              "    " + _grey(f"{_bar(eff(e))} {eff(e):.2f}  "), width)
    print()
    _say("A dormant episode comes back if something in a conversation recalls it strongly enough.")
    print()


def show_last():
    eps = load("")
    if not eps:
        _title("the newest episode")
        _say("No episodes yet: they are written when a project closes.")
        print()
        return
    e = max(eps, key=lambda x: x.get("id", ""))
    import re as _re
    model = e.get("model", "") or ""
    model = _re.sub(r"[-_.]gguf(?=:|$)", "", model, flags=_re.I).replace(":", " (", 1)
    model = model + ")" if "(" in model else model
    _title("the newest episode", _dot().join(x for x in (_when(e.get("ts", "")), model) if x))
    width = _width()
    _field("goal", e.get("goal", ""), width)
    _field("outcome", _dot().join([str(e.get("outcome", "") or "?"),
                                   f"importance {e.get('importance', '?')}",
                                   f"strength {e.get('salience', '?')}"]), width)
    if e.get("keywords"):
        _field("keywords", ", ".join(e.get("keywords") or []), width)
    if e.get("narrative"):
        _field("what happened", e.get("narrative", ""), width)
    if e.get("interpretation"):
        _field("what it means", e.get("interpretation", ""), width)
    for s in e.get("surprises") or []:
        _field("surprise", s, width)
    print()
    print("  " + _grey(e.get("id", "")))
    print()


def do_jump(months):
    """The time machine's core: age every episode by `months` simulated months
    by shifting its timestamps back by months * half_life days (1 half-life =
    1 month), then sweep, then advance the story clock. The half-life itself is
    never touched — after the jump, physical time = story time again."""
    if months <= 0:
        print("--jump: months must be > 0")
        return
    shift = D.timedelta(days=months * hl)

    shifted = 0
    for sub in ("", "dormant"):
        pat = (os.path.join(d, "episodes", sub, "ep_*.json") if sub
               else os.path.join(d, "episodes", "ep_*.json"))
        for f in sorted(glob.glob(pat)):
            try:
                with open(f, encoding="utf-8") as fh:
                    e = json.load(fh)
                changed = False
                for k in ("ts", "last_recalled", "dormant_since"):
                    v = e.get(k)
                    if not v:
                        continue
                    try:
                        t = D.datetime.strptime(v, ISO).replace(tzinfo=D.timezone.utc)
                    except Exception:
                        continue
                    e[k] = (t - shift).strftime(ISO)
                    changed = True
                if changed:
                    with open(f, "w", encoding="utf-8") as fh:
                        json.dump(e, fh, indent=2, ensure_ascii=False)
                    shifted += 1
            except Exception:
                continue
    print(f"aged {shifted} episode(s) by {months:g} month(s) "
          f"({months * hl:g} days at the current {hl:g}-day half-life)")

    # sweep at the (unchanged) configured pace
    sys.path.insert(0, os.path.join(_HERE, "..", "core"))
    import episodes as estore
    r = estore.sweep(store=os.path.join(d, "episodes"),
                     learnings_path=os.path.join(d, "learnings.json"))
    if r["dormant"]:
        print(f"{len(r['dormant'])} episode(s) moved to dormant: "
              + ", ".join(r["dormant"]))
    else:
        print("no episode crossed the dormancy threshold")
    if r["deleted"]:
        print(f"{len(r['deleted'])} episode(s) hard-deleted: "
              + ", ".join(r["deleted"]))
    if r.get("delete_blocked"):
        print(f"hard deletion skipped: {r['delete_blocked']}")

    # story clock: settle pending real time, then add the jump
    os.makedirs(d, exist_ok=True)
    c = clock_read()
    now_s = now.strftime(ISO)
    if c is None:
        c = {"months": 0.0, "ts": now_s, "half_life_days": hl, "started": now_s}
    else:
        c["months"] = float(c.get("months", 0.0)) + clock_pending_months(c)
        c["ts"] = now_s
        c["half_life_days"] = hl
    c["months"] += months
    with open(CLOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
    print(clock_line())


def show_sweep():
    """The only mutating subcommand: runs the real dormancy sweep now
    (core/episodes.sweep) instead of waiting for the next `pragma "..."`
    session to trigger it as a side effect of consolidation."""
    sys.path.insert(0, os.path.join(_HERE, "..", "core"))
    import episodes as estore
    store = os.path.join(d, "episodes")
    lp = os.path.join(d, "learnings.json")
    r = estore.sweep(store=store, learnings_path=lp)
    if r.get("delete_blocked"):
        print(f"hard deletion skipped: {r['delete_blocked']}")
    if not r["dormant"] and not r["deleted"]:
        print("(nothing crossed the dormancy threshold — nothing to sweep)")
        return
    if r["dormant"]:
        print(f"{len(r['dormant'])} episode(s) moved to dormant:")
        for eid in r["dormant"]:
            print(f"  - {eid}")
    if r["deleted"]:
        print(f"{len(r['deleted'])} episode(s) hard-deleted "
              f"(EPISODE_DELETE_AFTER_DAYS): {', '.join(r['deleted'])}")


if "--beliefs" in _flags:
    show_beliefs()
elif "--diff" in _flags:
    show_diff()
elif "--oblio" in _flags or "--dormant" in _flags:
    show_oblio()
elif "--last" in _flags:
    show_last()
elif "--sizes" in _flags:
    show_sizes()
elif "--sweep" in _flags:
    show_sweep()
elif "--clock-set" in _flags:
    clock_set()
elif "--jump" in _flags:
    do_jump(_jump_months)
else:
    show_map()
