# critic_validate

Evaluate an output against semantic quality criteria using a critic LLM.

---

## Parameters

- `output` (str): Text or JSON to evaluate.
- `criteria` (str): Natural language description of quality criteria.
- `model` (str, optional, default ""): Model for the critic call; defaults to `config.DEFAULT_MODEL`.

## Returns

JSON string `{"verdict": "PASS"|"WARN"|"FAIL", "reason": "...", "suggestions": [...]}` or `"ERROR: ..."`.

## Notes

- Complements `schema_validate` (structural) with semantic evaluation.
- `PASS`: fully meets all criteria; `WARN`: minor gaps; `FAIL`: fails one or more critical criteria.
- The critic uses temperature 0.0 for deterministic verdicts.
