# MCP Integration Notes

This file documents the Python-side tool contract expected from the MCP servers configured in `.vscode/mcp.json`.

## Servers

- `r-tools` (stdio): `Rscript --vanilla tools/server.R`
- `ohdsi_hecate` (http/sse): remote server for concept lookup

## Canonical tool names

Expected in `phenotyping_agent/mcp_tools.py`:

- `listConceptSets`
- `getConceptSetsCapr`
- `getCohortCount`
- `getDatabaseDescription`
- `countConceptSetPersonOverlap`
- `describeMeasurementValues`
- `computeIncidenceRate`
- `validateCapr`
- `convertCaprToJson`
- `generateCohort`
- `evaluateCohort`
- `samplePatientProfile`

## Important argument conventions from `tools/server.R`

- `caprCode` for cohort tooling is a single top-level `cohort(...)` expression.
- `countConceptSetPersonOverlap` expects `caprCode` as an array of standalone `cs(...)` expressions.
- `describeMeasurementValues` expects `caprCode` as an array of standalone `cs(...)` expressions.
- `evaluateCohort` requires both `cohortId` and `phenotype`.

## Expectation-gated diagnostics

Python facade maps diagnostics to expectation types:

- `getCohortCount` -> `cohortCount`
- `computeIncidenceRate` -> `incidenceRate`
- `countConceptSetPersonOverlap` -> `conceptSetOverlap`
- `describeMeasurementValues` -> `measurementValues`
- `evaluateCohort` -> `keeperMetrics`

The wrapper refuses these calls if no matching expectation has been pre-registered.

## Current implementation status

- Tool-name assertion: implemented
- Tool-call logging (`tool_calls.jsonl`): implemented
- `evaluateCohort` hard cap: implemented
- Real `langchain-mcp-adapters` transport: not implemented yet

## Live integration TODO (next)

1. Add a real MCP client path that reads `.vscode/mcp.json`.
2. Keep `FakeToolClient` as the `--dry-run` path.
3. Preserve existing wrapper enforcement (expectations, budgets, logging).
4. Add integration tests that mock name discovery and argument marshaling.

