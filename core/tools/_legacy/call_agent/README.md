# call_agent

Delegate a task to a specialized sub-agent via HTTP POST.

---

## Parameters

- `agent_name` (str): Name of the sub-agent (used for logging and error messages).
- `task` (str): Description of the task to execute.
- `input_data` (str, optional, default ""): JSON string with structured input data for the sub-agent.
- `endpoint` (str, optional, default ""): Base URL of the sub-agent, e.g. `"http://localhost:8001"`. Required.

## Returns

The sub-agent's result string, or `"ERROR: ..."` if the call fails or `endpoint` is missing.

## Notes

- POSTs to `<endpoint>/run` with body `{"task": ..., "input": ...}`.
- Expects the response JSON to have a `"result"` key; otherwise returns the full JSON.
- Timeout is 120 seconds.
