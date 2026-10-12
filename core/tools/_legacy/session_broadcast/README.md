# session_broadcast

Publish a typed event on the session channel via WebSocket or stdout stub.

---

## Parameters

- `event_type` (str): Event name/type string.
- `payload` (str, optional, default ""): Event payload content.
- `channel` (str, optional, default "default"): Channel name for routing.

## Returns

`"broadcast OK: channel/event_type"` if a handler is registered, `"broadcast stub: ..."` otherwise, or `"broadcast ERROR: ..."` on handler failure.

## Notes

- In Pattern B (FastAPI), a real WebSocket handler must be registered at startup via `register_broadcast_handler()` imported from this module.
- Without a handler, the skill falls back to printing to stdout (useful for standalone baseline testing).
- `register_broadcast_handler` is a module-level function, not registered as a skill.
