#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""What you will probably type next: one line, in grey, on the empty prompt.

A FACULTY, not a second model. The obvious way to do this is a small model
kept running beside the big one, and it costs a second server, a slice of
VRAM, a fourth role in the catalogue and one more thing that has to be alive
for a prompt to be drawn. The other obvious way is to ask the agent for the
suggestions along with its answer, which is worse in a quieter way: it makes
the model writing the reply also think about what you will ask next, and on a
reasoning model that lands inside the reasoning of the reply. The thing you
care about pays for the thing you do not.

So it is one short call of its own, after the answer is on the screen, on the
`recall` role - the one already meant to be fast, and the one /configure lets
you tell not to reason. It never blocks the prompt: the line comes back
immediately and the guess arrives into it, or does not.

ONE guess, not a list. A list is a menu, and a menu where you are about to
type is something to read before you can start. This is meant to be the line
you were going to write anyway, already written: tab takes it, and typing
anything at all ignores it.

OFF unless asked for. It is an extra call per turn on a local model that is
shared with everything else, and a machine with one slot pays for it in the
queue. /configure turns it on, once, for the whole harness.
"""
from __future__ import annotations

import os

import config
import llm_client
from json_parser import extract_json

_SYSTEM = """You read the last exchange of a conversation between a person and
an assistant, and you write the ONE line the PERSON is most likely to type
next.

YOU ARE WRITING AS THE PERSON, NOT AS THE ASSISTANT. What you write goes
straight into their input box, so it has to be in their voice: they say "I"
and "me", and they call the assistant "you". An offer of help is always
wrong - that is the assistant's line, not theirs.

    wrong: How can I help you today?
    right: What can you do for me?
    wrong: Let me know if you want me to try the other model.
    right: Try it with the other model

Rules:
- Write it as they would type it: a question or an instruction, not a topic,
  and not a sentence about them.
- It must ASK FOR something or TELL the assistant to do something. "Thanks,
  I will look" and "ok, got it" are things people type and are useless as
  suggestions: nothing happens when they are sent.
- Build it out of what is in front of you. The likeliest next line names
  something the answer just mentioned - a file, a command, a number, a choice
  offered - and asks for the next step on it.
- Write it in the language the person is using, whatever it is.
- Keep it short: one line, no more than about twelve words.
- If the exchange gives you nothing to build on - a greeting, a goodbye, an
  answer that closed the subject - answer with an empty string. A wrong guess
  costs more than no guess: it sits in the input box where the person is
  about to type, and they have to delete it.

Answer as JSON: {"question": "..."}"""

_SCHEMA = {
    "__name__": "suggestion",
    "type": "object",
    "properties": {
        "question": {"type": "string"},
    },
    "required": ["question"],
    "additionalProperties": False,
}

# What the model is shown of the turn. Enough for the thread to be legible,
# short enough that the call stays cheap: this runs on every turn.
ASKED_CHARS = 700
ANSWERED_CHARS = 1400
MAX_CHARS = 90

# A SUGGESTION HAS A SHELF LIFE. The harness's own timeout is generous because
# a consolidation is worth waiting for; this is not. A guess that arrives after
# the line has been typed is worth nothing, and against a server that accepts
# the connection and then says nothing the default would leave one thread
# blocked per turn, stacking up for as long as the endpoint stayed sick.
TIMEOUT = int(os.environ.get("SUGGEST_TIMEOUT", "") or 20)


def enabled() -> bool:
    """Off unless /configure said otherwise, for the whole harness."""
    try:
        return bool(config.suggest_next())
    except Exception:
        return False


def next_question(asked: str, answered: str, model=None) -> str:
    """The one thing the person is likeliest to type next, or "" - never raises.

    ONE, not a list. A list is a menu, and a menu on the input line is a thing
    to read before you can type; this is meant to be the line you were going
    to write anyway, already written. If it is not that, it is wrong, and the
    right number of wrong guesses to show is none.

    A suggestion that fails is a suggestion that is not offered. Nothing here
    is worth interrupting a conversation for, and the caller runs it off the
    critical path precisely so that a slow or dead endpoint costs nothing.
    """
    asked, answered = (asked or "").strip(), (answered or "").strip()
    if not asked or not answered:
        return ""
    # The instruction is repeated at the END, where it is nearest the answer:
    # a model that read "write as the person" at the top of a system prompt
    # and then a whole exchange can arrive at the reply having slipped back
    # into the voice it usually speaks in. Measured the hard way - it offered
    # "How can I help you today?".
    payload = (f"THE PERSON SAID:\n{asked[:ASKED_CHARS]}\n\n"
               f"THE ASSISTANT ANSWERED:\n{answered[:ANSWERED_CHARS]}\n\n"
               f"Now write the next line THE PERSON types. Their voice, not "
               f"the assistant's.")
    try:
        with llm_client.faculty("SUGGESTER"):
            raw = llm_client.call_llm(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                timeout=TIMEOUT,
                **config.memory_call("select"),
                response_schema=_SCHEMA,
            )
        data = extract_json(raw) or {}
    except Exception:
        return ""
    # A model that answers the question instead of asking it produces a
    # paragraph. One line is the contract; anything longer is not a suggestion
    # and would not fit on the input line anyway.
    q = " ".join(str(data.get("question") or "").split())
    return q if len(q) <= MAX_CHARS else ""
