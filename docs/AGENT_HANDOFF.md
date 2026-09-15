# Agent Handoff

This document helps future coding agents continue implementation of the autonomous Python cohort developer in `phenotyping_agent/`.

## Current architecture

The graph is a real LangGraph `StateGraph` (`phenotyping_agent/graph.py`) with conditional edges:

```
intake -> survey -> design -> write_capr -> generate -> measure -> assess
             ^          |                                            |
             |  (capr repair budget exhausted)                       |
             |                                                       +-- iterate --> design
             +-- diagnose <-- evaluate <---- (gated) ----------------+-- evaluate
                                                                     +-- done ----> report
```

Nodes all share the signature `run(state, deps) -> dict` and return **state deltas**, never the
whole state. `AgentState.ledger` uses the `merge_ledger` reducer, which replaces an entry with the
same iteration number so `evaluate` and `diagnose` can amend the entry `assess` already wrote.

Core support modules:

- `phenotyping_agent/state.py`: pydantic models, structured LLM output schemas (`DesignOutput`,
  `AssessOutput`, `DiagnoseOutput`), typed `AgentState`, `merge_ledger` reducer
- `phenotyping_agent/llm_runtime.py`: `LLMRuntime.structured/text/chat`, schema-repair retries,
  event logging, prompt loading, stubbed-tier dispatch
- `phenotyping_agent/stubs.py`: deterministic stand-ins used when a tier is `provider="none"`
- `phenotyping_agent/context.py`: shared prompt context, ledger compaction, expectation rules
- `phenotyping_agent/parsing.py`: tolerant parsing of MCP payloads into typed models
- `phenotyping_agent/deps.py`: `NodeDeps` (config, tools, runtime, ledger store, `BudgetGuard`)
- `phenotyping_agent/mcp_tools.py`: tool facade, expectation gating, per-node allow-lists
  (`restrict_to`), call counters used by the gate, tool-name assertion, evaluate budget cap
- `phenotyping_agent/capr_checks.py`: static checks for concept-ID provenance and shape
- `phenotyping_agent/ledger.py`: JSONL persistence (upsert by iteration) and markdown rendering
- `phenotyping_agent/cli.py`: `run` (with `--resume`) and `list-tools`

## LLM behaviour

| Node | Tier | Output |
|---|---|---|
| `intake` | fast (only to derive a missing phenotype name) | text |
| `survey` | none (deterministic) | - |
| `design` | reasoning | tool sub-loop (<=6 turns) then `DesignOutput` |
| `write_capr` | fast | Capr text, <=4 repair turns fed static-check/validator errors |
| `generate`, `measure` | none (deterministic) | - |
| `assess` | reasoning | `AssessOutput` (verdicts, mechanisms, next action) |
| `evaluate` | none (deterministic sampling) | - |
| `diagnose` | reasoning | `DiagnoseOutput` (mechanism-backed failure modes) |
| `report` | fast | narrative, wrapped in deterministic evidence sections |

Every call is logged to `runs/<id>/llm_events.jsonl` with prompt, response, usage and latency.

**Dry run is hermetic.** With `--dry-run`, `build_config` ignores tier environment variables
unless a tier flag is passed explicitly, and each LLM node falls back to `stubs.py`. Without that
rule an ambient `REASONING_TIER_PROVIDER` combined with the placeholder model name would send a
real network request from a supposedly offline run.

## Guarantees enforced in code, not by prompt

1. Expectation gating: diagnostic tools refuse to run without a matching registered expectation.
   `design` additionally fails loudly if `cohortCount`/`incidenceRate` were not pre-registered.
2. Phase 2 -> 3 gate: `assess` can propose `evaluate`, but Python requires a non-zero cohort, an
   overlap diagnostic, an incidence diagnostic for the current cohort, a written readiness
   rationale and remaining evaluation budget. Unmet preconditions are recorded in
   `LedgerEntry.gate_blockers` and force `iterate`.
3. Budgets: design iterations, Capr repairs, the hard 3-call `evaluateCohort` cap, profile counts
   and wall clock. `BudgetGuard` is consulted in the routing functions; exhaustion routes to
   `report` with partial results.
4. Concept-ID provenance: snippets enter the registry verbatim; `validate_capr_static` rejects any
   concept ID that is not in a registry snippet, and the error is fed back as a repair turn.
5. Anti-overfitting: `diagnose` drops failure modes with no stated mechanism.
6. Per-node tool allow-lists via `ToolFacade.restrict_to`.

## Milestone status against `docs/LANGGRAPH_AGENT_PLAN.md`

- M1 Plumbing: done (package, CLI, tool-name assertion, live MCP transport)
- M2 Fixtures: partial (`FakeToolClient` + defaults; **no recorded real fixture set yet**)
- M3 Codegen path: done (design -> Capr -> static checks -> `validateCapr` -> bounded repair)
- M4 Phase 2 loop: done (loop, expectations, gate, budgets, ledger)
- M5 Phase 3: done (evaluation, error-profile sampling, `diagnose`, hard cap)
- M6 Report/polish: done (`report.md`, `final_cohort.json`, `design_<n>.json`, `cohort_<n>.R`)

## Known remaining gaps

1. **No recorded fixtures.** `FakeToolClient` returns hard-coded defaults, so `--dry-run`
   exercises the plumbing but not realistic data. Record real ALF responses into
   `tests/fixtures/<toolName>.json` next. Note that `tests/test_live_payload_shapes.py` pins the
   shapes the R server actually returns, including the ones the fake never produces.
2. **No live acceptance run yet.** The prompts have not been exercised against a real model.
   Expect prompt iteration, especially in `design`. MCP connectivity itself is verified:
   `list-tools --live` discovers all 12 R tools plus 5 `hecate_*` tools.
3. Checkpointing is optional: `SqliteSaver` is used only when `langgraph-checkpoint-sqlite` is
   installed (`pip install -e ".[checkpoint]"`). Without it `--resume` does nothing.
4. Token/cost budget is plumbed (`BudgetGuard.max_total_tokens`) but not yet wired to a CLI flag.
5. The Hecate tools *are* exposed live but are not bound into the `design` node, because the fake
   client does not provide them and doing so would break dry-run/live parity. Adding them means
   extending `FakeToolClient` at the same time.
6. `describeMeasurementValues` and `countConceptSetPersonOverlap` wrappers pass whole registry
   snippet lists; per-target granularity is coarse.
7. Reasoning-style models (o-series) are not supported by `llm_client.py`, which always sends
   `temperature`/`top_p`. Use chat models such as `gpt-4o`.

## Live-run hazards already handled

These were found by reading `tools/server.R` and cannot be reproduced in `--dry-run`:

- `getCohortCount` returns **two different shapes**. With inclusion rules it returns per-rule
  attrition; with none - the common first-iteration case - it returns `personCount`/`entryCount`.
  Misreading the second as the first yields a cohort size of 0 and the Phase 3 gate would reject
  a perfectly good cohort forever. Handled in `parsing.parse_attrition`.
- `getConceptSetsCapr` returns **no name column**; rows come back in request order and unmatched
  names are silently dropped. Positional mapping is therefore only safe when every name resolves,
  otherwise snippets shift onto the wrong names and the cohort gets the wrong concept IDs.
  `ToolFacade.fetch_concept_set_snippets` falls back to one call per name when counts disagree.
- `computeIncidenceRate` returns a bare string when there is no observation time. Preserved as
  `IncidenceSummary.note` so `assess` sees the message instead of "no data".
- `computeIncidenceRate` already returns Overall, Age and Sex strata, so no extra call is needed.
- Per-tool read timeouts and a single retry for transport errors are in `mcp_tools.py`.
  `generateCohort` and `evaluateCohort` are never retried.
- The KEEPER budget is consumed only after a **successful** call, so a phenotype with no
  reference cohort does not burn one of the three permitted evaluations.

## Recommended next steps

1. Do a short live run (`--max-iterations 2`) and read `llm_events.jsonl` before spending a full
   8-iteration budget.
2. Record real MCP fixtures for ALF from that run's `tool_calls.jsonl`.
3. Check the two decay modes the plan warns about (unfalsifiable expectations and self-serving
   grading) using the verdict tally in `report.md`.
4. Wire a `--max-tokens` flag to `BudgetGuard`.
