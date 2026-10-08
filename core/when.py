# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# when.py - the days a request names.
#
# "What did I decide last week", "back in June", "the day before yesterday":
# a request can name a stretch of time, and a search by words or by meaning
# cannot follow it there. Words find the episode that SAYS "last week";
# meaning finds what the request is about, whenever it happened. Neither
# knows that last week was the 6th to the 12th.
#
# This module only reads the words. Given a request and today's date it
# returns the stretches of days the request names - first day, last day, and
# the words that named them - and nothing else: who gets a seat because of it
# is the curator's business (curator._dated).
#
# No model is asked. An expression of time is a closed class of words, in the
# two languages a request comes in; a model asked "which days does this mean"
# has to be told today's date, subtract, and know what day of the week it is,
# and gets each of the three wrong often enough to matter.
#
# WHAT IS LEFT OUT, ON PURPOSE:
#   - today: the latest episodes always have seats of their own.
#   - "last time", "the other session": that is recency, not a date - same seats.
#   - a bare weekday ("on Friday", "il venerdì"): as often a habit or a plan as
#     a day gone by. Only "last Friday" / "venerdì scorso" names one.
#   - anything in the future.

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

_MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
              "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_MONTHS_EN = ["january", "february", "march", "april", "may", "june",
              "july", "august", "september", "october", "november", "december"]
_DAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
_DAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUMBERS = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
            "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
            "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(\d{1,3}|" + "|".join(sorted(_NUMBERS, key=len, reverse=True)) + r")"
_MIT = "(" + "|".join(_MONTHS_IT) + ")"
_MEN = "(" + "|".join(_MONTHS_EN) + ")"
_DIT = "(" + "|".join(d.replace("ì", "[ìi]'?") for d in _DAYS_IT) + ")"
_DEN = "(" + "|".join(_DAYS_EN) + ")"


def _n(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBERS.get(word, 1)


def _month_index(name: str) -> int:
    name = name.lower()
    return (_MONTHS_IT.index(name) if name in _MONTHS_IT else _MONTHS_EN.index(name)) + 1


def _weekday_index(name: str) -> int:
    """Monday is 0. By the first three letters, which no two days share in
    either language - and which an accent left off does not change."""
    return ["lun", "mar", "mer", "gio", "ven", "sab", "dom",
            "mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(name.lower()[:3]) % 7


def _month(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _latest_month(today: date, month: int, year: str | None, completed: bool = False) -> tuple[date, date]:
    """The month a name refers to: the year given, or else the latest one that
    has begun - or, for "last June", the latest one that is over."""
    if year:
        return _month(int(year), month)
    y = today.year
    if month > today.month or (completed and month == today.month):
        y -= 1
    return _month(y, month)


def _latest_day(today: date, month: int, day: int, year: str | None) -> tuple[date, date] | None:
    try:
        if year:
            y = int(year)
            d = date(y + 2000 if y < 100 else y, month, day)
        else:
            d = date(today.year, month, day)
            if d > today:
                d = date(today.year - 1, month, day)
    except ValueError:
        return None
    return d, d


def _third(span: tuple[date, date], part: str) -> tuple[date, date]:
    first, last = span
    if part in ("inizio", "inizi", "early", "beginning of", "start of"):
        return first, first.replace(day=10)
    if part in ("fine", "late", "end of"):
        return first.replace(day=21), last
    return first.replace(day=11), first.replace(day=20)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _back(today: date, days: int, slack: int = 0) -> tuple[date, date]:
    return today - timedelta(days=days + slack), today - timedelta(days=max(days - slack, 0))


def _last(today: date, days: int) -> tuple[date, date]:
    return today - timedelta(days=days), today


def _months_back(today: date, k: int) -> tuple[date, date]:
    y, m = today.year, today.month - k
    while m < 1:
        y, m = y - 1, m + 12
    return _month(y, m)


# Each rule: a pattern over the request, lower-cased, and what it means given
# today. Tried in this order, and a stretch of the request that one rule has
# read is not read again by a later one - "l'altro ieri" is not also "ieri",
# and "14 luglio" is not also the whole of July.
_RULES: list[tuple[re.Pattern, object]] = []


def _rule(pattern: str):
    def add(fn):
        _RULES.append((re.compile(r"(?<!\w)(?:" + pattern + r")(?!\w)", flags=re.IGNORECASE | re.UNICODE), fn))
        return fn
    return add


# ── a day by its date ────────────────────────────────────────────────────────

@_rule(r"(20\d\d)-(\d\d)-(\d\d)")
def _iso(m, today):
    try:
        d = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None
    return d, d


@_rule(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})")
def _slashed(m, today):
    return _latest_day(today, int(m[2]), int(m[1]), m[3]) if 1 <= int(m[2]) <= 12 else None


@_rule(r"(\d{1,2})°? (?:di )?" + _MIT + r"(?: (?:del )?(20\d\d))?")
def _day_month_it(m, today):
    return _latest_day(today, _month_index(m[2]), int(m[1]), m[3])


@_rule(_MEN + r" (\d{1,2})(?:st|nd|rd|th)?(?:,? (20\d\d))?")
def _month_day_en(m, today):
    return _latest_day(today, _month_index(m[1]), int(m[2]), m[3])


@_rule(r"(\d{1,2})(?:st|nd|rd|th)? (?:of )?" + _MEN + r"(?:,? (20\d\d))?")
def _day_month_en(m, today):
    return _latest_day(today, _month_index(m[2]), int(m[1]), m[3])


# ── part of a month, a month ─────────────────────────────────────────────────

@_rule(r"(inizio|inizi|metà|fine) (?:di |del mese di |d')?" + _MIT + r"(?: (?:del )?(20\d\d))?")
def _part_it(m, today):
    return _third(_latest_month(today, _month_index(m[2]), m[3]), m[1].lower())


@_rule(r"(early|mid|late|beginning of|start of|middle of|end of)[ -]" + _MEN + r"(?: (20\d\d))?")
def _part_en(m, today):
    return _third(_latest_month(today, _month_index(m[2]), m[3]), m[1].lower())


@_rule(r"(?:da|dal|dal mese di) " + _MIT + r"(?: (?:del )?(20\d\d))?")
def _since_it(m, today):
    return _latest_month(today, _month_index(m[1]), m[2])[0], today


@_rule(r"since " + _MEN + r"(?: (20\d\d))?")
def _since_en(m, today):
    return _latest_month(today, _month_index(m[1]), m[2])[0], today


@_rule(_MIT + r" (scorso|passato)|(?:lo scorso|il passato) " + _MIT)
def _last_month_named_it(m, today):
    return _latest_month(today, _month_index(m[1] or m[3]), None, completed=True)


@_rule(r"last " + _MEN)
def _last_month_named_en(m, today):
    return _latest_month(today, _month_index(m[1]), None, completed=True)


@_rule(r"(?:a|ad|in|di|nel|nel mese di|durante|per tutto) " + _MIT + r"(?: (?:del )?(20\d\d))?")
def _month_it(m, today):
    return _latest_month(today, _month_index(m[1]), m[2])


@_rule(r"(?:in|during|back in|throughout) " + _MEN + r"(?: (20\d\d))?")
def _month_en(m, today):
    return _latest_month(today, _month_index(m[1]), m[2])


@_rule("(?:" + _MIT + "|" + _MEN + r") (20\d\d)")
def _month_year(m, today):
    return _month(int(m[3]), _month_index(m[1] or m[2]))


# ── days counted back from today ─────────────────────────────────────────────

@_rule(r"l'altro ?ieri|altro ?ieri|ieri l'altro|avantieri|(?:the )?day before yesterday")
def _two_days(m, today):
    return _back(today, 2)


@_rule(r"ieri(?: sera| mattina| pomeriggio| notte)?|yesterday(?: evening| morning| afternoon)?|last night|stanotte")
def _yesterday(m, today):
    return _back(today, 1)


@_rule(_NUM + r" (?:giorni|giorno|gg) fa|" + _NUM + r" days? ago")
def _days_ago(m, today):
    k = _n((m[1] or m[2]).lower())
    return _back(today, k, slack=1 if k >= 3 else 0)


@_rule(r"un paio di giorni fa|a couple of days ago")
def _couple_days(m, today):
    return today - timedelta(days=3), today - timedelta(days=1)


@_rule(r"(?:qualche|alcuni|pochi) giorn[oi] fa|giorni fa|l'altro giorno|a few days ago|some days ago|several days ago|the other day")
def _few_days_ago(m, today):
    return today - timedelta(days=7), today - timedelta(days=1)


@_rule(r"(?:ultimi|scorsi|passati) " + _NUM + r" giorni|(?:last|past) " + _NUM + r" days")
def _last_n_days(m, today):
    return _last(today, _n((m[1] or m[2]).lower()))


@_rule(r"(?:ultimi|scorsi|passati) giorni|giorni scorsi|giorni passati|in questi giorni|"
       r"(?:last|past) (?:few|couple of) days|recent days")
def _last_few_days(m, today):
    return _last(today, 5)


# ── weeks ────────────────────────────────────────────────────────────────────

@_rule(r"ultima settimana|ultimi sette giorni|(?:the|this) (?:last|past) week|over the (?:last|past) week")
def _rolling_week(m, today):
    return _last(today, 7)


@_rule(r"settimana scorsa|scorsa settimana|settimana passata|passata settimana|last week|(?:the )?previous week|the week before")
def _last_week(m, today):
    start = _monday(today) - timedelta(days=7)
    return start, start + timedelta(days=6)


@_rule(r"questa settimana|in settimana|this week")
def _this_week(m, today):
    return _monday(today), today


@_rule(r"(?:weekend scorso|scorso weekend|fine settimana scorso|scorso fine settimana|last weekend)")
def _last_weekend(m, today):
    saturday = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
    if today.weekday() == 6:                       # said on a Sunday, it is the one before
        saturday = today - timedelta(days=8)
    return saturday, saturday + timedelta(days=1)


@_rule(r"(?:ultime|scorse|passate) " + _NUM + r" settimane|(?:last|past) " + _NUM + r" weeks")
def _last_n_weeks(m, today):
    return _last(today, 7 * _n((m[1] or m[2]).lower()))


@_rule(r"un paio di settimane fa|a couple of weeks ago")
def _couple_weeks(m, today):
    return _back(today, 14, slack=4)


@_rule(r"(?:qualche|alcune|poche) settiman[ae] fa|a few weeks ago|some weeks ago|several weeks ago")
def _few_weeks_ago(m, today):
    return today - timedelta(days=35), today - timedelta(days=14)


@_rule(_NUM + r" settiman[ae] fa|" + _NUM + r" weeks? ago")
def _weeks_ago(m, today):
    return _back(today, 7 * _n((m[1] or m[2]).lower()), slack=3)


# ── months, years ────────────────────────────────────────────────────────────

@_rule(r"ultimo mese|ultimi trenta giorni|(?:the|this) (?:last|past) month|over the (?:last|past) month")
def _rolling_month(m, today):
    return _last(today, 30)


@_rule(r"mese scorso|scorso mese|mese passato|last month|(?:the )?previous month|the month before")
def _last_month(m, today):
    return _months_back(today, 1)


@_rule(r"questo mese|this month")
def _this_month(m, today):
    return today.replace(day=1), today


@_rule(r"(?:ultimi|scorsi|passati) " + _NUM + r" mesi|(?:last|past) " + _NUM + r" months")
def _last_n_months(m, today):
    return _last(today, 30 * _n((m[1] or m[2]).lower()))


@_rule(r"(?:qualche|alcuni|pochi) mes[ei] fa|a few months ago|some months ago|several months ago")
def _few_months_ago(m, today):
    return today - timedelta(days=150), today - timedelta(days=45)


@_rule(_NUM + r" mes[ei] fa|" + _NUM + r" months? ago")
def _months_ago(m, today):
    return _back(today, 30 * _n((m[1] or m[2]).lower()), slack=10)


@_rule(r"anno scorso|scorso anno|anno passato|last year")
def _last_year(m, today):
    return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)


@_rule(r"(?:nel|in|del|durante il) (20\d\d)")
def _year(m, today):
    if int(m[1]) >= today.year:                    # the year we are in names no stretch of it
        return None
    return date(int(m[1]), 1, 1), date(int(m[1]), 12, 31)


# ── a weekday gone by, and "lately" ──────────────────────────────────────────

@_rule(_DIT + r" (?:scors[oa]|passat[oa])|(?:lo scorso|la scorsa|scorso|scorsa) " + _DIT + r"|last " + _DEN)
def _last_weekday(m, today):
    k = _weekday_index(m[1] or m[2] or m[3])
    d = today - timedelta(days=(today.weekday() - k) % 7 or 7)
    return d, d


@_rule(r"di recente|recentemente|ultimamente|negli ultimi tempi|recently|lately|of late")
def _lately(m, today):
    return _last(today, 7)


def windows(text: str, today: date) -> list[tuple[date, date, str]]:
    """The stretches of days a request names: (first day, last day, the words
    that named it), in the order the rules found them. None of it later than
    today; nothing for a request that names no time.
    """
    low = " ".join(str(text or "").lower().replace("’", "'").split())
    taken = [False] * len(low)
    out: list[tuple[date, date, str]] = []
    for pattern, means in _RULES:
        for m in pattern.finditer(low):
            a, b = m.span()
            if any(taken[a:b]):
                continue
            try:
                span = means(m, today)
            except Exception:
                span = None
            if not span:
                continue
            for k in range(a, b):
                taken[k] = True
            first, last = span
            last = min(last, today)
            if first > last:                      # all of it still to come
                continue
            if (first, last) not in [(x, y) for x, y, _ in out]:
                out.append((first, last, m.group(0)))
    return out
