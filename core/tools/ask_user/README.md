# ask_user

Ask the user a question. In a live conversation, you ask by ending the turn.

---

## Parameters

- `topic` (str): The question, or what you need to know.
- `context` (str, optional, default ""): Why you are asking, in one sentence.
- `mode` (str, optional, default "input"): `"input"` for a free answer, `"confirm"` for yes or no.

## Returns

It depends on where Pragma is running:

- **Live conversation.** `confirm` asks the person at the terminal and returns `"yes"` or `"no"`. Any other mode returns an instruction to end the turn with your question as the reply: the answer arrives as their next message.
- **Batch run.** Nobody is there. `confirm` returns `"no"`; any other mode returns a notice to proceed on your best judgment or conclude with what is missing. Neither is ever an authorization.
- **Browser interface.** The question appears in the page and the typed answer is returned; `"(no response)"` after ten minutes, `"(stopped)"` if the task is stopped.

## Do not

- Ask for what a skill can find out (`list_dir`, `read_file`, `file_outline`).
- Ask several questions in one call: one topic per call.
- Ask trivial questions the user should not need to answer ("should I read the file?" — just read it).
- Treat a `"no"`, a notice, or silence as permission for a destructive action.
