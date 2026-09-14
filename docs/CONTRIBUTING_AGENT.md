# Contributing Guide for Coding Agents

This guide defines safety and quality constraints for edits to `phenotyping_agent/`.

## Non-negotiable invariants

1. `caprCode` submitted to cohort tools must be one top-level `cohort(...)` expression.
2. No top-level assignments in cohort expressions.
3. Do not invent concept IDs; IDs must come from retrieved concept-set snippets.
4. Keep expectation gating active for diagnostic tools.
5. Keep the hard cap on `evaluateCohort` (default 3 per run).

## Edit checklist

Before changing behavior:

- Read `docs/LANGGRAPH_AGENT_PLAN.md`
- Read `docs/AGENT_HANDOFF.md`
- Confirm tool contract in `tools/server.R`

When implementing:

- Preserve `--dry-run` as a reliable, offline path.
- Keep changes small and traceable by module.
- Prefer explicit state transitions over implicit side effects.

After implementing functional code changes:

```powershell
python -m pytest -q
python -m phenotyping_agent.cli run --clinical-definition "acute liver failure.txt" --dry-run
```

## PR/commit quality bar

- Tests pass locally.
- No regressions in expectation-gating behavior.
- No regressions in concept-ID static checks.
- `runs/` remains ignored.
- If MCP tool names changed, update `EXPECTED_TOOLS` and this doc in the same change.

## Suggested next tasks

1. Replace fake-only MCP path with dual-mode fake/live transport.
2. Wire structured LLM calls for `design` and `assess`.
3. Add checkpoint/resume with SQLite.
4. Align artifacts and gating details fully with plan M1-M6.

