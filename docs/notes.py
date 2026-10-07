# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""The hand-written half of the generated reference.

docs/build.py reads the code for what the code knows - which variables are
read, their defaults, the commands, the skills, where each prompt is - and
reads THIS file for what it cannot know: what a variable or a prompt is for,
in one line.

The two are checked against each other. A variable the code reads and this
file does not describe stops the build, and so does a description of a
variable nothing reads any more; the same holds for the prompts. That check
is the reason the descriptions live here and not in a page someone edits by
hand.

One line each. A reference says what a thing is; the reasons are in the
comment beside it, in the file the page links to.

Also here: the few sentences that open and close a generated page.
"""

# What the page says before the tables.
CONFIG_INTRO = """\
Every setting is an environment variable. Where its value comes from:

- **The project's own settings**, for the variables marked *project setting*.
  They are kept in `~/.pragma/registry.json`, one set per project, and a
  project that has never set one has none. Opening a project sets each of them
  from there and clears whatever the shell held, so a value left over from
  another project cannot leak in. On Windows `pragma -Set <key> <value>`
  writes one; the steps a turn may take are asked by `/settings` everywhere.
- **The shell** the launcher was started from, for every other variable.
- **`.env`** in the repository root, for anything neither of those named.
  See [`.env.example`](../../.env.example).
- **The default** in the table.

The model server is the exception. Once `/configure` has written
`~/.pragma/endpoints.json`, the addresses, the sampling of each endpoint and
which role uses which are read from that file, and `LLM_BASE_URL`,
`LLM_API_KEY` and `DEFAULT_MODEL` are no longer read.

Most of these never need touching. The ones a new installation meets are in
the first two groups.
"""

# (key, title, one line under the title). The order is the order on the page.
CONFIG_GROUPS = [
    ("endpoint", "The model server",
     "Used until `/configure` writes its own file; the timeouts apply either way."),
    ("sampling", "Sampling and reasoning",
     "What a request sends when the endpoint's own table says nothing."),
    ("budgets", "Budgets",
     "How large a context, an answer and a single action may be."),
    ("compaction", "When the conversation outgrows the window",
     "A batch run summarises its older steps; a conversation turns its older turns into memory."),
    ("watchdogs", "Watchdogs",
     "What stops a model that is repeating itself."),
    ("recall", "What memory brings to a turn", ""),
    ("memory", "How memory is written and how it fades", ""),
    ("options", "Optional faculties",
     "Both are off unless turned on in `/configure`; the variables override that for one run."),
    ("storage", "Where things are kept", ""),
    ("launcher", "Set by the launcher",
     "Written for the conversation it starts. Listed so that nobody sets them by hand."),
    ("dev", "For development and tests", ""),
]

# name -> (group, what it is) or (group, what it is, default as it should read).
# The third element is for defaults the code computes from other settings.
CONFIG = {
    # -- endpoint ---------------------------------------------------------
    "LLM_BASE_URL": ("endpoint",
        "Address of the OpenAI-compatible server, ending in `/v1`."),
    "LLM_API_KEY": ("endpoint",
        "Key sent to that server. Local servers usually need none."),
    "DEFAULT_MODEL": ("endpoint",
        "Model name sent in the request. A single-model server ignores it."),
    "PRAGMA_ENDPOINTS": ("endpoint",
        "Another file to read the endpoint catalogue from.",
        "`~/.pragma/endpoints.json`"),
    "LLM_TIMEOUT": ("endpoint",
        "Seconds before one model call is abandoned."),
    "LLM_STREAM_CALLS": ("endpoint",
        "`0` makes every call a blocking request, for a server whose streaming misbehaves."),
    "ENDPOINT_PROBE_TIMEOUT": ("endpoint",
        "Seconds a connection may take before an endpoint counts as not connected."),
    "PRAGMA_NO_ENDPOINT_PROBE": ("endpoint",
        "`1` skips asking the server for its context window at start-up."),

    # -- sampling ---------------------------------------------------------
    "DEFAULT_TEMPERATURE": ("sampling",
        "Temperature of the agent's calls. `server` leaves it to the endpoint."),
    "TOP_K": ("sampling", "Sampling knob, sent only when set."),
    "TOP_P": ("sampling", "Sampling knob, sent only when set."),
    "MIN_P": ("sampling", "Sampling knob, sent only when set."),
    "SAMPLING_PROFILE": ("sampling",
        "`general` or `coding` picks that row of the endpoint's table; `server` sends "
        "nothing; `manual` sends the four variables above.",
        "the endpoint's own choice"),
    "SUMMARY_TEMPERATURE": ("sampling",
        "Temperature of the call that summarises older steps."),
    "AGENT_THINK": ("sampling",
        "`on` or `off` overrides, for one run, whether the model reasons before answering.",
        "the endpoint's own choice"),
    "MEMORY_THINK_BUDGET": ("sampling",
        "Characters of reasoning after which a memory call is asked again without it. `0` removes the cap.",
        "derived from `MEMORY_MAX_TOKENS`"),
    "RECALL_THINK_BUDGET": ("sampling",
        "The same cap for the recall, which runs while you wait."),
    "MEMORY_SEED": ("sampling",
        "Seed sent with every memory call, so the same prompt gives the same answer."),

    # -- budgets ----------------------------------------------------------
    "CONTEXT_WINDOW": ("budgets",
        "The model's context window, in tokens.",
        "asked of the server, else 65536"),
    "MAX_TOKENS": ("budgets",
        "Output budget of one agent reply. It has to hold a whole file being written."),
    "SKILL_MAX_TOKENS": ("budgets",
        "Output budget of a model call made inside a skill.",
        "same as `MAX_TOKENS`"),
    "SKILL_MAX_TOKENS_RATIO": ("budgets",
        "Sets `SKILL_MAX_TOKENS` as a fraction of `MAX_TOKENS` instead. `0` is unset."),
    "MEMORY_MAX_TOKENS": ("budgets",
        "Output budget of the memory faculties.",
        "same as `SKILL_MAX_TOKENS`"),
    "MAX_STEPS": ("budgets",
        "Steps a turn may take before the agent is told to conclude. "
        "A project opened from the launcher has its own number: 50, or what `/settings` was given."),
    "WRITE_FILE_SOFT_LIMIT": ("budgets",
        "Bytes above which `write_file` advises smaller edits."),
    "WRITE_FILE_HARD_LIMIT": ("budgets",
        "Bytes above which `write_file` refuses a single call.",
        "twice `MAX_TOKENS`, at most 20000"),
    "OBSERVATION_SOFT_LIMIT": ("budgets",
        "Characters above which a tool's output is shortened in the history. `0` disables."),
    "PRAGMA_MD_MAX_CHARS": ("budgets",
        "Characters of the workspace's `PRAGMA.md` that are passed to the agent."),

    # -- compaction -------------------------------------------------------
    "COMPRESS_TOKENS": ("compaction",
        "Prompt tokens above which the agent summarises its older steps.",
        "same as `CHAT_COMPACT_TOKENS`"),
    "MAX_MESSAGES": ("compaction",
        "Also summarise above this many messages. `0` counts nothing."),
    "MESSAGES_RECENT": ("compaction",
        "Most recent messages kept word for word when the rest is summarised."),
    "RECENT_MAX_CHARS": ("compaction",
        "Ceiling on those recent messages, in characters.",
        "a quarter of the window"),
    "MESSAGE_COMPRESS_TRUNC": ("compaction",
        "Characters of each message handed to the summariser."),
    "CHAT_COMPACT_TOKENS": ("compaction",
        "Prompt tokens above which a conversation hands its older turns to memory.",
        "about 80% of the window"),
    "CHAT_COMPACT_CHARS": ("compaction",
        "The same trigger in characters, used until the server has counted a request.",
        "half the window"),
    "CHAT_COMPACT_MARGIN": ("compaction",
        "Tokens kept free below the top of the window when that trigger is computed."),
    "CHAT_KEEP_TURNS": ("compaction",
        "Most recent turns left in the conversation after it is compacted."),
    "CHAT_TRANSCRIPT_CHARS": ("compaction",
        "Characters of each model reply kept in the transcript memory is written from."),

    # -- watchdogs --------------------------------------------------------
    "REASONING_LOOP_ENABLED": ("watchdogs",
        "Whether a reasoning that repeats itself is cut."),
    "REASONING_LOOP_WINDOW": ("watchdogs",
        "Characters of reasoning compared at a time."),
    "REASONING_LOOP_CHECK_EVERY": ("watchdogs",
        "Characters of reasoning between two comparisons."),
    "REASONING_LOOP_THRESHOLD": ("watchdogs",
        "Repetitions of the same passage that cut the reasoning."),
    "ACTION_LOOP_ENABLED": ("watchdogs",
        "Whether the same failing tool call, repeated, draws a warning to the agent."),
    "ACTION_LOOP_THRESHOLD": ("watchdogs",
        "Identical failing calls in a row before that warning."),
    "ERROR_RATE_WINDOW": ("watchdogs",
        "Recent tool calls looked at for a run of errors across different tools."),
    "ERROR_RATE_THRESHOLD": ("watchdogs",
        "Fraction of those that must have failed to draw the warning."),

    # -- recall -----------------------------------------------------------
    "CURATOR_ENABLED": ("recall",
        "Whether a model call chooses what to recall. Off, the best keyword matches are used as they are."),
    "CURATOR_CANDIDATES_EPISODES": ("recall",
        "Episodes offered to that choice."),
    "CURATOR_CANDIDATES_LEARNINGS": ("recall",
        "Beliefs offered to that choice."),
    "CURATOR_CANDIDATES_RECENT": ("recall",
        "Of the episodes offered, how many are simply the most recent."),
    "CURATOR_MAX_FRAGMENTS": ("recall",
        "Most fragments that may be placed in front of the agent for one turn."),
    "PRAGMA_EMBED_URL": ("recall",
        "Address of an embedding server, ending in `/v1`. With one, what is offered to that choice is "
        "found by meaning and not by the words it shares with the request. `/configure` sets one for "
        "the machine, and that one is used first; this is for a script."),
    "PRAGMA_EMBED_MODEL": ("recall",
        "The model name to ask that server for, when it hosts several."),
    "PRAGMA_EMBED_TIMEOUT": ("recall",
        "Seconds an embedding call may take before the search goes by words instead."),
    "CURATOR_OFFERED_EPISODES": ("recall",
        "`few`, `medium` or `many`: how many episodes are offered to that choice, said in a word. "
        "Set, it decides `CURATOR_CANDIDATES_EPISODES` and `CURATOR_CANDIDATES_RECENT`. "
        "`/settings` in a project sets it."),
    "CURATOR_OFFERED_LEARNINGS": ("recall",
        "The same, for beliefs: set, it decides `CURATOR_CANDIDATES_LEARNINGS`."),
    "CURATOR_TAKEN_EPISODES": ("recall",
        "`few`, `medium` or `many`: how readily episodes are taken from what was offered. "
        "Unset is `few`, and with both kinds at `few` recall is what it has always been."),
    "CURATOR_TAKEN_LEARNINGS": ("recall",
        "The same, for beliefs."),
    "MEMORY_NARRATIVE_CHARS": ("recall",
        "Characters shown of what a recalled episode records."),
    "MEMORY_INTERPRETATION_CHARS": ("recall",
        "Characters shown of what a recalled episode is taken to mean."),
    "EPISODES_RECALL_TOP_K": ("recall",
        "Episodes returned when the choice above is switched off."),
    "LEARNINGS_RECALL_TOP_K": ("recall",
        "Beliefs returned when the choice above is switched off."),
    "EPISODE_WORKSPACE_BOOST": ("recall",
        "Advantage, in the keyword match, of an episode written in the folder being worked in."),

    # -- memory -----------------------------------------------------------
    "SALIENCE_BASE": ("memory",
        "Salience a new episode starts from."),
    "SALIENCE_SURPRISE_WEIGHT": ("memory",
        "Added to it for each surprise the episode records."),
    "SALIENCE_IMPORTANCE_WEIGHT": ("memory",
        "Weight of the episode's importance score in its starting salience."),
    "SALIENCE_CAP": ("memory",
        "Upper bound of the starting salience."),
    "EPISODE_RECALL_BOOST": ("memory",
        "How much being recalled strengthens an episode."),
    "EPISODE_RECALL_RULE": ("memory",
        "`asymptotic` or `additive`: how that boost is applied."),
    "EPISODE_RECALL_PROCEDURAL_FACTOR": ("memory",
        "Fraction of the boost earned by a recall made only to see how something is done. `1.0` treats every recall alike."),
    "EPISODE_IMPORTANCE_ANCHORS": ("memory",
        "Stored episodes shown as a scale when a new one is scored. `0` shows none."),
    "EPISODE_DECAY_HALF_LIFE_DAYS": ("memory",
        "Days for an episode's salience to halve when it is not recalled. `0` disables decay."),
    "EPISODE_DORMANT_THRESHOLD": ("memory",
        "Salience below which an episode goes dormant."),
    "EPISODE_DELETE_AFTER_DAYS": ("memory",
        "Days dormant before an episode nothing refers to is deleted. `0` never deletes."),
    "SEMANTIC_MIN_SOURCES": ("memory",
        "Distinct episodes a new belief must rest on."),
    "SEMANTIC_CONFIRM_BONUS": ("memory",
        "Confidence a belief gains each time it is confirmed."),
    "SEMANTIC_CONTRADICT_MALUS": ("memory",
        "Confidence it loses each time it is contradicted."),
    "SEMANTIC_RETIRE_CONTRADICTIONS": ("memory",
        "Contradictions after which a belief is retired."),
    "RECONSOLIDATION_ENABLED": ("memory",
        "Whether later sessions may revise what earlier episodes and beliefs mean."),
    "RECONSOLIDATE_MAX_EPISODES": ("memory",
        "Related past episodes re-read each time a session is written down."),
    "RECONSOLIDATE_REFORMULATE_AT": ("memory",
        "Contradictions after which a belief is reworded rather than retired.",
        "same as `SEMANTIC_RETIRE_CONTRADICTIONS`"),
    "RECONSOLIDATE_BRIDGE_MIN_SOURCES": ("memory",
        "Revised source episodes, in one session, that make a belief a candidate for rewording."),
    "RECONSOLIDATE_REFUSE_DRIFT": ("memory",
        "`true` leaves an episode's interpretation as it was when a revision would bring it closer to the new episode than to its own. Needs an embedding server."),
    "AUTO_REFLECT": ("memory",
        "Whether a reflection pass runs after a successful task."),
    "BATCH_SEGMENT": ("memory",
        "`1` has a batch run judged before it becomes an episode. Unset, every batch run with `--memory` writes one."),
    "MEMORY_SCHEMA": ("memory",
        "`0` stops the memory faculties from asking the server to constrain their JSON."),

    # -- options ----------------------------------------------------------
    "SUGGEST_NEXT": ("options",
        "`on` or `off`: whether the line you will probably type next is offered, in grey.",
        "the choice made in `/configure`"),
    "SUGGEST_TIMEOUT": ("options",
        "Seconds after which that guess is given up on."),
    "CRITIC": ("options",
        "`on` or `off`: whether a turn that changed something is checked against the request before the answer is delivered.",
        "the choice made in `/configure`"),
    "CRITIC_MAX_ROUNDS": ("options",
        "Times that check may send the same turn back."),
    "CRITIC_EVIDENCE_CHARS": ("options",
        "Characters of the turn's record the check is shown."),

    # -- storage ----------------------------------------------------------
    "PRAGMA_DATA_DIR": ("storage",
        "Folder holding the memory in use. The launcher sets it to the open project's own.",
        "`~/.pragma`"),
    "LEARNINGS_PATH": ("storage",
        "File holding the beliefs.",
        "`learnings.json` in the data folder"),
    "PRAGMA_PLUGINS": ("storage",
        "Folder the home screen reads plugins from.",
        "`~/.pragma/plugins`"),

    # -- launcher ---------------------------------------------------------
    "PRAGMA_PROJECT": ("launcher",
        "Name of the open project."),
    "PRAGMA_WORKSPACE": ("launcher",
        "Folder of the open project. A batch run uses it when `--cwd` is not given."),
    "PRAGMA_REQUEST": ("launcher",
        "File through which the conversation asks the launcher to do something on the way out."),
    "PRAGMA_SESSION_ID": ("launcher",
        "Identifies a session, so that writing it down twice produces one episode."),
    "PRAGMA_ACCENT": ("launcher",
        "Accent colour of the screens, as `R;G;B`.",
        "`178;132;255`"),

    # -- dev --------------------------------------------------------------
    "PRAGMA_DEBUG": ("dev",
        "`1` prints diagnostic output."),
    "PRAGMA_LOOK": ("dev",
        "`classic` draws a turn the way it was drawn before: the name of each tool, "
        "its arguments and its output. Unset, the turn is a ledger."),
    "PRAGMA_ALLOW_SELF_MODIFY": ("dev",
        "`true` lets a session write inside Pragma's own repository, which is otherwise refused."),
    "PRAGMA_CLOCK": ("dev",
        "Freezes the clock the memory reads at an ISO instant."),
    "PRAGMA_CLOCK_OFFSET": ("dev",
        "Shifts that clock by a number of seconds."),
    "PRAGMA_CONSOLIDATE_SYNC": ("dev",
        "`1` writes memory in the foreground on leaving, instead of in a background process."),
    "PRAGMA_CRITIC_SNAPSHOT": ("dev",
        "Folder that receives a copy of the workspace when a turn first delivers, for tests."),
}

# Read from the environment by the code, and not Pragma's own.
NOT_PRAGMA = {"TERM"}


# ── the decisions ────────────────────────────────────────────────────────────

DECISIONS_INTRO = """\
One short record for each decision that shaped Pragma: what the situation
was, what was decided, and what follows from it. They are here so that a
choice which looks odd today can be traced to the problem it answered —
before someone undoes it and meets the problem again.

The reasons for smaller choices are in the code, in the comment at the top of
the file that makes them.
"""

DECISIONS_OUTRO = """\
## Adding one

Copy the newest record, give it the next number, and write the three parts.
Keep it to a screen. Then run `python docs/build.py`, which adds it to the
list above.

A record is not rewritten once it is true. A decision that changes gets a
*new* record saying which one it replaces, and the old one changes only its
status line, to `superseded by N`. What was decided and why stays readable
for as long as the code that came out of it is around.
"""


# ── the prompts ──────────────────────────────────────────────────────────────

PROMPTS_INTRO = """\
Every instruction Pragma gives a model is written in the code, in English,
and this is where each one is. To read one, open the file.

A call is made in one of four roles, and the role decides which server
answers it: see [Architecture](../explanation/architecture.md#which-server-answers-which-call).
"""

PROMPTS_OUTRO = """\
The agent's prompt is not one string. It is put together when a conversation
or a run starts: `build_system_prompt`, then what the way of running adds,
then the project's rules, then `session_block`.

The loop also speaks to the model in its own voice while a turn runs — when
the step budget is spent, when a call keeps failing the same way. Those lines
are in [`core/react.py`](../../core/react.py), beside the code that sends
them.
"""

# "file:name" -> (the role its calls are made in, what it is for).
# A string at the top of a module whose name says it is a prompt must be here:
# the build stops on one that is not. The ones built by a function are listed
# by hand, and the build checks that the name still exists.
PROMPTS = {
    "agent/prompts.py:build_system_prompt": ("agent",
        "The agent's system prompt: what it is, how it works in a folder, how it answers. "
        "The same for every way of running Pragma."),
    "agent/chat.py:chat_policy": ("agent",
        "Added in a conversation: how to answer a person across many turns."),
    "agent/prompts.py:project_contract": ("agent",
        "Carries the workspace's `PRAGMA.md` into the prompt, with what it overrides."),
    "agent/prompts.py:session_block": ("agent",
        "The folder and the date. Last, so that everything before it is the same "
        "from one session to the next."),
    "core/memory.py:SYSTEM_PROMPT_SUMMARY": ("agent",
        "Summarises the older steps of a turn that has grown too long."),
    "core/skills/ask_user/skill.py:_ASK_SYSTEM": ("agent",
        "Words a question for the person, where the question is not asked by ending the turn."),
    "agent/server.py:_SUMMARIZE_SYSTEM": ("agent",
        "The browser interface's summary of a thread that has grown too long."),

    "core/curator.py:_CURATOR_SYSTEM": ("recall",
        "Chooses, before a turn, what the memory holds that is worth showing."),
    "core/curator.py:_curator_system": ("recall",
        "The same instructions, with the paragraph on how much to take rewritten for a "
        "project that asked its recall to take more than a few."),
    "core/suggest.py:_SYSTEM": ("recall",
        "Guesses the line you will type next. Optional."),

    "core/segmenter.py:_SYSTEM": ("memory",
        "Decides which turns of a conversation are worth keeping."),
    "core/skills/episode_consolidate/skill.py:_EPISODE_SYSTEM": ("memory",
        "Writes an episode from what was kept."),
    "core/skills/episode_consolidate/skill.py:_SEMANTIC_SYSTEM": ("memory",
        "Draws beliefs from what recurs across episodes."),
    "core/reconsolidate.py:_EPISODIC_SYSTEM": ("memory",
        "Revises what an earlier episode is taken to mean."),
    "core/reconsolidate.py:_SEMANTIC_SYSTEM": ("memory",
        "Rewords a belief that has been contradicted."),
    "core/reconsolidate.py:_REVIEW_SYSTEM": ("memory",
        "Checks a belief against episodes whose meaning was revised."),
    "core/skills/session_reflect/skill.py:_REFLECT_SYSTEM": ("memory",
        "A reflection pass over a finished task."),

    "core/critic.py:_SYSTEM": ("critic",
        "Checks the work of a turn against what was asked. Optional."),
}

# What the keyboard does. Not in any table the code keeps, so it is written
# here; the commands themselves are read from the code.
KEYS = [
    ("ctrl+D", "In a project: close it and hand the conversation to the memory. "
               "At home: leave. In a menu or a page: go back."),
    ("ctrl+C", "Stop the turn that is running; the project stays open. "
               "In a menu: go back."),
    ("tab, or right arrow", "Take the suggested next line, when one is shown."),
    ("tab", "After a `/`: complete the command."),
    ("arrows, a digit, a first letter", "Move in a menu. Enter selects."),
]
