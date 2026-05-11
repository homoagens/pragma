from __future__ import annotations

import llm_client
from json_parser import extract_json


_ASK_SYSTEM = """You are a communication assistant for an AI agent.
Given a topic and optional context, formulate the clearest possible question to ask a human user.

Respond with ONLY a JSON object:
{
  "question": "the formulated question, clear and specific",
  "hint":     "optional brief hint on expected format or valid values (empty string if none)"
}

Keep the question concise, direct, and unambiguous.
For confirm mode, phrase it as a yes/no question.
For choice mode, list the options clearly inside the question."""


def ask_user(topic: str = "", context: str = "", mode: str = "input",
             prompt: str = "", question: str = "") -> str:
    """
    [H] Pause execution and request input or approval from the user.
    Deterministic mechanism: input() from console.
    LLM judgment: formulates the question clearly and in context.

    topic   : subject to ask about (also accepts: prompt, question)
    context : additional context for formulating the question
    mode    : "input" (free text) | "confirm" (y/n) | "choice" (option list)
    Returns : user answer as a string; "yes"/"no" for confirm mode
    """
    # Accept common aliases for topic
    if not topic:
        topic = prompt or question
    # 1. Build the message for the LLM [H]
    user_msg = f"Topic: {topic}"
    if context:
        user_msg += f"\nContext: {context}"
    if mode == "confirm":
        user_msg += "\nMode: yes/no — phrase as a question the user can answer with y or n"
    elif mode == "choice":
        user_msg += "\nMode: choice — list available options clearly inside the question"

    # 2. LLM formulates the optimal question [H]
    try:
        raw = llm_client.call_llm(
            messages=[
                {"role": "system", "content": _ASK_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.0,
        )
        formulated = extract_json(raw)
    except Exception:
        # Fallback: use topic directly without LLM formulation
        formulated = {"question": topic, "hint": ""}

    question = formulated.get("question", topic)
    hint     = formulated.get("hint", "")

    # 3. Show the question and collect the answer [D]
    header = f"\n[INPUT REQUEST]\n{question}"
    if hint:
        header += f"\n({hint})"

    if mode == "confirm":
        answer = input(f"{header} [y/n]: ").strip().lower()
        return "yes" if answer in ("y", "yes", "1") else "no"
    else:
        return input(f"{header}\n> ").strip()
