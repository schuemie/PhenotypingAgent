# Agent Handoff

This document helps future coding agents continue implementation of the autonomous Python cohort developer in `phenotyping_agent/`.

## Current architecture

Execution flow (implemented in `phenotyping_agent/graph.py`):

1. `intake` (`phenotyping_agent/nodes/intake.py`)
2. `survey_concept_sets` (`phenotyping_agent/nodes/survey.py`)
3. `design` (`phenotyping_agent/nodes/design.py`)
4. `write_capr` (`phenotyping_agent/nodes/write_capr.py`)
5. `generate` (`phenotyping_agent/nodes/generate.py`)
6. `measure` (`phenotyping_agent/nodes/measure.py`)
7. `assess` (`phenotyping_agent/nodes/assess.py`)
8. optional `evaluate` (`phenotyping_agent/nodes/evaluate.py`)
9. `report` (`phenotyping_agent/nodes/report.py`)

Core support modules:

- `phenotyping_agent/state.py`: pydantic models for `Design`, `Expectation`, `LedgerEntry`, and agent state typing
- `phenotyping_agent/mcp_tools.py`: tool facade, expectation gating, tool-name assertion, tool-call logging, evaluate budget cap
- `phenotyping_agent/capr_checks.py`: static checks for concept-ID provenance and cohort expression shape
- `phenotyping_agent/ledger.py`: JSONL persistence and markdown rendering
- `phenotyping_agent/cli.py`: `run` and `list-tools` commands

## Deterministic vs planned LLM behavior

Current implementation is intentionally deterministic in key nodes for dry-run reliability:

- Deterministic now: `design`, `write_capr`, `assess`, `evaluate` decision logic
- Planned LLM/structured output later: `design`, `assess`, `diagnose`, and richer `report`

Prompt placeholders exist in `phenotyping_agent/prompts/` but are not yet wired to model calls.

## Milestone status against `docs/LANGGRAPH_AGENT_PLAN.md`

- M1 Plumbing: partial (package, CLI, tool-name assertion; real MCP transport not yet wired)
- M2 Fixtures: partial (`FakeToolClient` + fixture directory; no recorded real fixture set yet)
- M3 Codegen path: partial (design -> Capr -> static checks -> `validateCapr`)
- M4 Phase 2 loop: partial (loop, expectations, budgets, ledger; no real MCP calls)
- M5 Phase 3: partial (evaluation path and hard cap implemented deterministically)
- M6 Report/polish: partial (`report.md` and `final_cohort.json` written)

## Known intentional gaps

1. `ToolFacade` currently uses `FakeToolClient` in all modes.
2. No `SqliteSaver` checkpointing yet.
3. No live model tier usage (`reasoning` vs `fast`) despite config placeholders.
4. `countConceptSetPersonOverlap` and `describeMeasurementValues` wrappers are simplified.
5. Gate criteria are simplified compared with the full plan.

## Recommended implementation order

1. Add real MCP adapter path (keep `--dry-run` fake path intact).
2. Introduce structured outputs for `design` and `assess`.
3. Add checkpoint/resume support.
4. Enrich phase gates and profile-sampling diagnostics.
5. Tighten report and artifact schema parity with plan.
