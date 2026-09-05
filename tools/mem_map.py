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

import json, glob, os, sys, datetime as D

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


def show_map():
    active, dormant = load(""), load("dormant")
    print(f"store: {d}")
    print(f"half-life {hl} d · dormancy threshold {thr}")
    print(clock_line() + "\n")
    print(f"{'zone':8}{'raw':>6}{'eff':>8} reint  episode")
    print("-" * 78)
    for z, eps in (("ACTIVE", active), ("DORMANT", dormant)):
        for e in sorted(eps, key=eff, reverse=True):
            r = len(e.get("interpretation_history") or [])
            print(f"{z:8}{e.get('salience',0):6.2f}{eff(e):8.3f} {r:>5}  {e.get('goal','')[:48]}")
    print(f"\nactive: {len(active)}   dormant (oblio): {len(dormant)}")


def show_beliefs():
    ents = learnings()
    if not ents:
        print("(no beliefs yet)")
        return
    for e in ents:
        nref = e.get("reformulations", 0)
        tag = f"  [reformulated x{nref}]" if nref else ""
        print(f"[{e.get('status','active'):7}] conf {e.get('confidence',0):.2f} "
              f"(+{e.get('confirmations',0)}/-{e.get('contradictions',0)}){tag}")
        print(f"    {e.get('text','')}")
        for h in e.get("text_history", []) or []:
            print(f"    was [{h.get('via','contradiction')}]: {h.get('text','')[:90]}")
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
    if not eps:
        print("(no episodes yet)")
        return
    ents = learnings()

    def stats(vals):
        vals = [v for v in vals if v]
        if not vals:
            return None
        return int(st.median(vals)), max(vals)

    # (label, values, what the curator lets through into the agent's prompt)
    rows = [
        ("goal",           [len(e.get("goal", "") or "") for e in eps],           None),
        ("narrative",      [len(e.get("narrative", "") or "") for e in eps],      400),
        ("interpretation", [len(e.get("interpretation", "") or "") for e in eps], 200),
        ("belief text",    [len(e.get("text", "") or "") for e in ents],          None),
    ]

    print(f"store: {d}")
    print(f"{len(eps)} episode(s), {len(ents)} belief(s)\n")
    print(f"{'field':18}{'median':>8}{'max':>8}   into the prompt")
    print("-" * 62)
    for label, vals, cap in rows:
        s = stats(vals)
        if not s:
            continue
        med, mx = s
        if cap is None:
            note = "in full (uncapped)"
        elif mx <= cap:
            note = f"in full (cap {cap})"
        else:
            note = f"CLIPPED at {cap}"
        print(f"{label:18}{med:>8}{mx:>8}   {note}")

    sizes = []
    for sub in ("", "dormant"):
        pat = os.path.join(d, "episodes", sub, "ep_*.json") if sub \
            else os.path.join(d, "episodes", "ep_*.json")
        sizes += [os.path.getsize(f) for f in glob.glob(pat)]
    if sizes:
        print(f"\n{'episode json':18}{int(st.median(sizes)):>8}{max(sizes):>8}   bytes on disk")

    cap = 6
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "core"))
        import config as _c
        cap = getattr(_c, "CURATOR_MAX_FRAGMENTS", 6)
    except Exception:
        pass
    print(f"\nrecall: at most {cap} fragments per task, ~600 chars each")
    print(f"        -> ~{cap * 600 // 1000:.0f} KB of prompt at worst, however "
          f"big the store grows.")
    if ents:
        longest = max(len(e.get("text", "") or "") for e in ents)
        if longest > 300:
            print(f"        NOTE: a belief is {longest} chars and beliefs are "
                  f"injected uncapped.")


def show_diff():
    hits = 0
    for e in load("") + load("dormant"):
        h = e.get("interpretation_history") or []
        if not h:
            continue
        hits += 1
        print(f"\n# episode: {e.get('goal','')}")
        for v in h:
            print(f"  before: {v.get('text','')}")
        print(f"  after : {e.get('interpretation','')}")
    for e in learnings():
        h = e.get("text_history") or []
        if not h:
            continue
        hits += 1
        print(f"\n# belief ({e.get('reformulations',0)} rewrites)")
        for v in h:
            print(f"  before [{v.get('via','contradiction')}]: {v.get('text','')}")
        print(f"  after : {e.get('text','')}")
    if not hits:
        print("(nothing has been reinterpreted or reformulated yet)")


def show_oblio():
    dorm = load("dormant")
    if not dorm:
        print("(oblio empty)")
        return
    for e in sorted(dorm, key=eff, reverse=True):
        print(f"raw {e.get('salience',0):.2f}  eff {eff(e):.3f}  "
              f"since {e.get('dormant_since','?')}  {e.get('goal','')}")


def show_last():
    eps = load("")
    if not eps:
        print("(no episodes yet)")
        return
    e = max(eps, key=lambda x: x.get("id", ""))
    print(f"id         : {e.get('id','')}")
    print(f"ts         : {e.get('ts','')}   model: {e.get('model','?')}")
    print(f"outcome    : {e.get('outcome','')}   importance: {e.get('importance','?')}"
          f"   salience: {e.get('salience','?')}")
    print(f"goal       : {e.get('goal','')}")
    print(f"keywords   : {', '.join(e.get('keywords',[]) or [])}")
    if e.get("surprises"):
        print("surprises  :")
        for s in e["surprises"]:
            print(f"  - {s}")
    print("narrative  :")
    for ln in (e.get("narrative", "") or "").splitlines():
        print(f"  {ln}")
    print(f"interpretation: {e.get('interpretation','')}")


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
elif "--oblio" in _flags:
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
