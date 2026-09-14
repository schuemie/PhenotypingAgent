# Operations

## Purpose

Run, troubleshoot, and validate the Python autonomous agent implementation in `phenotyping_agent/`.

## Local run commands

```powershell
python -m pip install -e .[dev]
python -m phenotyping_agent.cli list-tools --live
python -m phenotyping_agent.cli list-tools
python -m phenotyping_agent.cli run --clinical-definition "acute liver failure.txt" --dry-run
python -m pytest -q
```

Notes:

- `list-tools --live` uses `.vscode/mcp.json` and auto-spawns `r-tools` via stdio.
- You do not need to start `tools/server.R` manually for this path.

## Run artifacts

Each run writes to `runs/<run_id>/`:

- `report.md`
- `final_cohort.json`
- `ledger.jsonl`
- `tool_calls.jsonl`

`runs/` is intentionally gitignored.

## Common failures and fixes

### Expectation gating failed

Error shape:

- `Expectation gating failed for diagnostic='...'`

Meaning:

- A diagnostic tool was called without a matching pre-registered expectation.

Fix:

1. Register an `Expectation` before the diagnostic call.
2. Ensure `diagnostic` and `target` match the wrapper call exactly.

### Tool mismatch assertion

Error shape:

- `Tool mismatch. Missing=... Extra=...`

Meaning:

- Discovered tool names do not match `EXPECTED_TOOLS` in `phenotyping_agent/mcp_tools.py`.

Fix:

1. Confirm names exposed by `tools/server.R`.
2. Update `EXPECTED_TOOLS` only when the server contract intentionally changes.

### `evaluateCohort` budget exhausted

Meaning:

- Hard cap reached (`config.budgets.evaluate_calls`, default 3).

Fix:

- This is expected behavior; proceed to reporting path.

### Static Capr checks failed

Typical reasons:

- Unknown concept IDs not present in concept-set registry
- More than one `cohort(` expression
- Top-level assignment

Fix:

1. Ensure all concept IDs originate from retrieved concept-set snippets.
2. Emit one top-level `cohort(...)` expression only.
3. Keep helper assignments out of `caprCode`.

## Testing policy for changes

For any functional code change in `phenotyping_agent/`:

1. Run `python -m pytest -q`
2. Run one dry-run invocation and verify `report.md` is produced.

## Current runtime mode

- Implemented and validated: `--dry-run` with fake tool client
- Planned next: live MCP transport via `.vscode/mcp.json`
