from __future__ import annotations

import json


def call_agent(agent_name: str, task: str,
               input_data: str = "", endpoint: str = "") -> str:
    """
    [G] Delegate a task to a specialized sub-agent.
    HTTP mode: POST to <endpoint>/run with {task, input_data}.

    agent_name : name of the agent (for logging and identification)
    task       : description of the task to execute
    input_data : JSON string with structured data for the sub-agent
    endpoint   : base URL of the sub-agent (e.g. "http://localhost:8001")
    """
    if not endpoint:
        return (
            f"ERROR: endpoint is required for call_agent '{agent_name}'. "
            f"Example: endpoint='http://localhost:8001'"
        )

    try:
        import requests
        resp = requests.post(
            f"{endpoint}/run",
            json={"task": task, "input": input_data},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", json.dumps(data, ensure_ascii=False))
    except Exception as e:
        return f"ERROR: call to agent '{agent_name}' ({endpoint}) failed — {e}"
