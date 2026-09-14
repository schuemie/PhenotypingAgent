# Plan: Autonomous Python LangGraph Cohort-Developer Agent

## Documentation index

- Architecture and implementation status: `docs/AGENT_HANDOFF.md`
- Operations and troubleshooting: `docs/OPERATIONS.md`
- MCP tool contract and integration notes: `docs/MCP_INTEGRATION_NOTES.md`
- Coding guardrails for future agents: `docs/CONTRIBUTING_AGENT.md`

Implements the workflow of `.agents/skills/cohort-developer/SKILL.md` as an unattended
Python LangGraph application, using the existing MCP tools in `tools/server.R` and the
remote `ohdsi_hecate` server. No human in the loop.

> Tool names below are the **camelCase** names the MCP server actually exposes. Verified:
> `ellmer::tool()` derives the tool name from the R function name, so `tool(listConceptSets, ...)`
> is published as `listConceptSets`. Exposed tools: `listConceptSets`, `getConceptSetsCapr`,
> `getCohortCount`, `getDatabaseDescription`, `countConceptSetPersonOverlap`,
> `describeMeasurementValues`, `computeIncidenceRate`, `validateCapr`, `convertCaprToJson`,
> `generateCohort`, `evaluateCohort`, `samplePatientProfile`. `createNewConceptSet` is
> commented out of the server's tool list.

## 1. Design decisions (settled)

| # | Decision |
|---|---|
| 1 | Deterministic phase skeleton with LLM nodes producing structured output. Budgets, loops and the 3-evaluation cap are enforced in code, not by prompt compliance. |
| 2 | Nine nodes, with design (prose/spec) strictly separated from Capr code generation. |
| 3 | Structured pydantic ledger held in state, rendered into every LLM prompt. |
| 4 | Hard budgets on design iterations, Capr repairs, KEEPER evaluations, profiles, wall clock and cost. |
| 5 | `langchain-mcp-adapters` + `MultiServerMCPClient`, one long-lived `r-tools` stdio session, wrapped tools with logging/timeouts/budgets, per-node tool allow-lists. |
| 6 | Python 3.12 (uv), Azure OpenAI via the same macOS keyring entries as `server.R`, two model tiers. Tier config is provider-agnostic so Claude can be swapped in later. |
| 7 | Concept set snippets stored verbatim in a registry; static checks reject concept IDs not present in the registry. |
| 8 | SQLite checkpointer for crash tolerance / resume. **No** duplicate-design detection. |
| 9 | Phase 2 → 3 gate: coded preconditions plus an LLM clinical-plausibility judgement covering counts, attrition **and** incidence rates. |
| 10 | Phase 3 sampling of patient profiles is driven deterministically by the error profile; diagnoses must state a mechanism and an expected metric effect. |
| 11 | `CAPR_REFERENCE.md` read at runtime from the skill folder; per-node prompts live in the Python package. |
| 12 | v1 uses pre-computed concept sets + Hecate lookups. `createNewConceptSet` stays out of scope (it is not even exposed by the server today). |
| 13 | Six milestones, fixture-backed `--dry-run` mode, acceptance = unattended ALF run. |
| 14 | Every diagnostic tool call must be preceded by a registered, qualitative expectation (direction or plausible range + rationale). Enforced by the tool wrapper, not by prompt. Precise epidemiologic benchmarks may not be invented. |

## 2. Graph

```
intake → survey_concept_sets → design ⇄ (diagnostic tool sub-loop)
            ↓
         write_capr ⇄ (static checks + validateCapr, ≤4 repairs)
            ↓
         generate → measure → assess
            ├── iterate ──────────→ design
            ├── evaluate (gated) ─→ evaluate → diagnose → design
            └── done ─────────────→ report
```

### Nodes

1. **`intake`** (deterministic) — load the clinical definition file and phenotype name.
   Hard-fail if the clinical definition is missing: SKILL.md requires invoking the interactive
   `clinical-definition-refiner`, which is impossible without a human, and explicitly forbids
   inventing missing clinical criteria. Deriving the phenotype *name* from the definition is
   allowed; if the name is absent, a cheap LLM call derives it.
2. **`survey_concept_sets`** (deterministic) — `listConceptSets`, `getDatabaseDescription`.
3. **`design`** (LLM, reasoning tier, structured output) — produces/revises a `Design`:
   hypothesis, entry event, concept sets *by name*, inclusion rules, temporal logic. Bounded
   tool sub-loop with access to `getConceptSetsCapr`, Hecate concept lookup,
   `describeMeasurementValues` (Phase 1 step 2: units and value distributions before writing any
   value-based criterion) and `countConceptSetPersonOverlap`. Prose only — no code. Must register
   an `Expectation` before each diagnostic call (see §5).
4. **`write_capr`** (LLM, fast tier) — `Design` + concept set registry + `CAPR_REFERENCE.md`
   → one `cohort(...)` expression, concept sets inlined with `name = "..."`, no assignments.
   Static checks, then `validateCapr`; ≤4 repairs, each fed the previous code and error.
   Exhaustion returns to `design` with the errors (counts as a design iteration).
5. **`generate`** (deterministic) — `generateCohort` → cohort ID.
6. **`measure`** (deterministic) — `getCohortCount` (Phase 2 step 3) and `computeIncidenceRate`
   (Phase 2 step 4, unstratified plus age- and sex-stratified). Both gated on expectations the
   `design` node registered before `generate` ran.
7. **`assess`** (LLM, reasoning tier, structured output) — compares counts, attrition and
   incidence rates against the registered expectations and clinical knowledge, writes the ledger
   entry, returns `iterate | evaluate | done` with a rationale.
8. **`evaluate`** (deterministic + LLM) — `evaluateCohort`, error-profile-driven
   `samplePatientProfile` sampling, then a `diagnose` LLM step.
9. **`report`** (LLM, fast tier) — final Capr code, ledger narrative, metrics, limitations.
   `convertCaprToJson` output is written straight to file; per SKILL.md its content is **not**
   read back or verified by the agent.

## 3. State

```python
class AgentState(TypedDict):
    phenotype: str
    clinical_definition: str
    database_description: str
    available_concept_sets: list[ConceptSetSummary]
    concept_set_registry: dict[str, str]      # name -> verbatim cs(...) code
    current_design: Design | None
    current_capr: str | None
    current_cohort_id: int | None
    pending_expectations: list[Expectation]   # registered, not yet compared
    ledger: Annotated[list[LedgerEntry], operator.add]
    budgets: Budgets
    next_action: Literal["iterate", "evaluate", "done"]
    final_report: str | None
```

### Expectations

```python
class Expectation(BaseModel):
    diagnostic: Literal["cohortCount", "incidenceRate", "conceptSetOverlap",
                        "measurementValues", "keeperMetrics"]
    target: str                # concept set name, inclusion rule, stratum, or "overall"
    claim_kind: Literal["relational", "magnitude_band", "direction"]
    claim: str                 # e.g. "markedly higher in 70+ than in 40-50" (relational),
                               # "1-10 per 100,000 PY" (magnitude_band)
    would_falsify: str         # the observation that would count as a violation
    rationale: str
    basis: Literal["clinical_reasoning", "supplied_by_user", "retrieved_from_source"]
    source: str | None         # required when basis == "retrieved_from_source"
```

Design intent — the point of pre-registration is the *ordering*, not the accuracy. Fixing the
claim before the result arrives is what stops `assess` from constructing an equally plausible
story for any number it is shown. A poorly calibrated expectation still does that work; an
unfalsifiable one does not.

Rules enforced by the validator:

- When `basis == "clinical_reasoning"`, a numeric claim must be a `magnitude_band` spanning at
  least an order of magnitude. Point estimates are rejected. Precise figures are only accepted
  with `basis` of `supplied_by_user` or `retrieved_from_source` plus a populated `source`.
  Rationale: an invented figure like "2.3 per 100,000 PY" propagates into `report.md` where a
  later reader cannot distinguish it from a literature-derived benchmark.
- `would_falsify` must be non-empty and must name an observation, not a sentiment. This is the
  guard against the rule decaying into ritual ("plausible for a rare disease" costs a turn and
  tests nothing).
- At least one expectation per diagnostic should be `relational` where the diagnostic admits it.
  Relational claims (age gradient, sex ratio, "smaller than iteration 3", "this exclusion removes
  under 20%") need no external benchmark, cannot be hallucinated, and are usually more diagnostic
  than absolute rates — database incidence in a commercially insured, under-65-skewed population
  is not population incidence, so absolute literature figures are the wrong comparator even when
  they are correct.

### Ledger

```python
class LedgerEntry(BaseModel):
    iteration: int
    hypothesis: str
    change_from_previous: str
    design: Design
    capr_code: str
    cohort_id: int | None
    expectations: list[Expectation]   # what we predicted, before seeing results
    verdicts: list[ExpectationVerdict] # held / violated / uninformative, with observed value
    counts: AttritionSummary          # per-rule incremental / marginal / gain
    incidence_rates: IncidenceSummary # overall + age and sex strata
    keeper: KeeperMetrics | None
    interpretation: str               # did each expectation hold?
    next_action: Literal["iterate", "evaluate", "done"]
```

Rendered as a markdown table plus prose into every LLM prompt, with the instruction not to
re-test changes already present. Beyond ~15 entries, older non-evaluated entries are compacted
to one line each; evaluated iterations always keep full detail.

`assess` must grade every expectation explicitly:

```python
class ExpectationVerdict(BaseModel):
    expectation: Expectation
    observed: str                # the actual value, quoted
    verdict: Literal["held", "violated", "uninformative"]
    reasoning: str
```

`uninformative` is a first-class, encouraged verdict: the same model made the prediction and now
grades it, so without an explicit escape hatch it will drift toward "consistent with expectation"
for everything. The report tallies verdicts per iteration — a run where most expectations are
`uninformative` means the gate has decayed into ceremony and the prompts need work, which is
exactly the failure the tally makes visible.

## 4. Budgets (code-enforced)

| Budget | Value | On exhaustion |
|---|---|---|
| `design_iterations` | 8 | force transition to `evaluate` |
| `capr_repair_attempts` per design | 4 | back to `design` with validator errors |
| `evaluateCohort` calls | **3 (hard, per skill invocation)** | force `report` |
| `samplePatientProfile` per evaluation | 6 | — |
| wall clock | 2 h | checkpoint + report partial results |
| LLM cost/tokens | configurable | checkpoint + report partial results |

The evaluation cap is enforced by the Python tool wrapper, which raises once the budget is
spent — the model cannot burn it by accident. The counter is per run, matching SKILL.md's
"three times in total during the skill invocation".

Early exits: PPV and sensitivity both > 80%; or `design` declares the definition not
expressible in Capr/Circe (SKILL.md rule 4), in which case `report` explains the mismatch and
proposes a decomposition rather than shipping a silent approximation.

## 5. Expectation gating and the Phase 2 → 3 gate

**Expectation gating (applies throughout Phase 1 and 2).** The wrappers for
`getCohortCount`, `computeIncidenceRate`, `countConceptSetPersonOverlap`,
`describeMeasurementValues` and `evaluateCohort` refuse to execute unless a matching
`Expectation` is present in `state["pending_expectations"]`. The LLM registers one via a
dedicated `record_expectation` tool. On refusal the error message states what is missing, so the
repair path is automatic. After the call the expectation moves into the ledger entry alongside
the observed result — this is what makes `assess` a genuine test rather than post-hoc narration.

**Gate into Phase 3.** Coded preconditions:

1. A cohort was generated with a non-zero final count.
2. At least one `countConceptSetPersonOverlap` call has been made this run.
3. `computeIncidenceRate` has been called for the current cohort, with a registered expectation.
4. `assess` returned `next_action == "evaluate"` with a written readiness rationale.

LLM-judged plausibility (no hard thresholds — the model applies clinical and data-capture
knowledge): the count is plausible for the phenotype's rarity, every large attrition step has a
stated mechanism, and the unstratified **and** stratified incidence rates match the registered
expectations. Implausible results force another design iteration until the 8-iteration budget
forces the transition anyway.

## 6. Phase 3 details

1. `evaluateCohort` → sensitivity, specificity, PPV, confusion matrix.
2. Deterministic profile sampling via `samplePatientProfile`: PPV weak → 5 FP + 1 TP;
   sensitivity weak → 5 FN + 1 TP; both weak → 3 FP + 3 FN.
3. `diagnose` (LLM) outputs
   `failure_modes: list[{pattern, evidence_person_count, proposed_design_change, expected_metric_effect}]`.
4. Returns to `design` and reuses the whole Phase 2 machinery.
5. Anti-overfitting: a proposed change must cite a clinical or data-capture mechanism.
   Changes that only enumerate person-level quirks seen in the sampled profiles are rejected
   by `assess`.

## 7. MCP wiring

- Config read from `.vscode/mcp.json` so Copilot and the Python agent share one source of truth.
- `r-tools`: stdio, `Rscript --vanilla tools/server.R`, one long-lived session per run, calls
  serialized (single-threaded R process).
- `ohdsi_hecate`: streamable HTTP/SSE, individual concept lookups only.
- Every tool wrapped to: log args + result to `runs/<ts>/tool_calls.jsonl`, enforce budgets and
  expectation gating, apply per-tool timeouts (~30 min for `generateCohort`), retry transient
  connection errors once.
- Per-node allow-lists: `design` gets `getConceptSetsCapr`, `describeMeasurementValues`,
  `countConceptSetPersonOverlap`, Hecate lookup and `record_expectation`; `write_capr` gets only
  `validateCapr`; deterministic nodes call tools directly without an LLM.
- A startup assertion compares discovered tool names against the expected camelCase list and
  fails loudly on mismatch, so a future rename in `server.R` breaks at M1 rather than mid-run.
- `--dry-run` swaps in a fake in-process MCP server backed by recorded fixtures.

## 8. Concept-ID safety

- Concept set Capr snippets enter `state["concept_set_registry"]` **verbatim** from
  `getConceptSetsCapr` / Hecate; the design node refers to sets by name only.
- Before calling `validateCapr`, a Python static check asserts:
  - every integer concept ID in the emitted code appears in a registry snippet;
  - exactly one top-level `cohort(` call;
  - no top-level assignments.
- Violations are returned as repair feedback — cheaper and more specific than the R validator.
- Missing concept sets are recorded as a `concept_set_gap` in the ledger and flagged in the
  final report; `createNewConceptSet` is not exposed by the server and stays out of v1.

## 9. Persistence and artifacts

- `SqliteSaver` checkpointer at `runs/<ts>/checkpoint.db`, `thread_id` = run id, enabling resume
  after a crash without re-spending cohort generations or KEEPER evaluations.
- Artifacts: `ledger.jsonl`, `tool_calls.jsonl`, `design_<n>.json`, `cohort_<n>.R`, `report.md`,
  `final_cohort.json`.
- `runs/` added to `.gitignore`.

## 10. Repository layout

```
pyproject.toml                 # uv, python 3.12
phenotyping_agent/
  cli.py                       # typer: --clinical-definition, --phenotype, --max-iterations, --dry-run, --resume
  config.py                    # provider-agnostic model tiers, budgets, paths, mcp.json location
  state.py                     # TypedDict + pydantic models (Design, Expectation, LedgerEntry, ...)
  graph.py                     # StateGraph, conditional edges, checkpointer
  nodes/                       # intake, survey, design, write_capr, generate, measure, assess, evaluate, report
  mcp_tools.py                 # MultiServerMCPClient, wrappers, budgets, expectation gating, logging, allow-lists
  ledger.py                    # rendering + persistence
  prompts/*.md                 # one prompt file per LLM node
tests/
  fixtures/                    # recorded MCP responses (ALF)
runs/<timestamp>/              # gitignored artifacts + checkpoint.db
```

Dependencies: `langgraph`, `langchain-openai`, `langchain-mcp-adapters`, `pydantic`, `keyring`,
`typer`, `rich`, `pytest`. Credentials come from the existing keyring entries
(`genai_openai_endpoint`, `genai_api_gpt4_key`) — nothing new in git.

Models: reasoning tier for `design`, `assess`, `diagnose`; fast tier for `write_capr` repairs and
`report`. Tiers carry a `provider` field in `config.yaml` so an Anthropic tier can be swapped in
without touching node code.

## 11. Milestones

- **M1 Plumbing** — py3.12 venv, deps, `mcp_tools.py`, a `list-tools` CLI command proving stdio
  wiring, Azure credentials, and the camelCase tool-name assertion before any graph exists.
- **M2 Fixtures** — record real responses for ALF (`listConceptSets`, `getConceptSetsCapr`,
  `describeMeasurementValues`, `validateCapr`, `getCohortCount`, `computeIncidenceRate`,
  `countConceptSetPersonOverlap`, `evaluateCohort`, `samplePatientProfile`); build the fake MCP
  server for `--dry-run`.
- **M3 Codegen path** — `design` → `write_capr` → static checks → `validateCapr`, tested
  standalone against a hand-written ALF design. Highest-risk node, proven early.
- **M4 Phase 2 loop** — generate/measure/assess, expectation gating, ledger, budgets,
  checkpointer; end-to-end ALF run without touching `evaluateCohort`.
- **M5 Phase 3** — evaluation, profile sampling, diagnose, hard 3-call cap; full autonomous run.
- **M6 Report and polish** — `report.md`, `convertCaprToJson` output, README section.

**Acceptance for v1:** an unattended
`python -m phenotyping_agent --clinical-definition "acute liver failure.txt"` run completes,
produces a valid Capr definition, a coherent ledger in which every diagnostic is paired with a
prior expectation, at most 3 KEEPER evaluations, and PPV/sensitivity at least comparable to the
current Copilot-driven skill.

## 12. Open risks

- Phase 3 requires the reference cohort; `getKeeperReferenceCohortId` currently only supports
  Acute Liver Failure, so other phenotypes stop after Phase 2. The agent should detect this and
  report it rather than fail.
- Single-threaded R MCP server: any long Databricks call blocks the whole run; timeouts must be
  generous and the wrapper must not silently retry a cohort generation.
- Reasoning-model latency plus cohort generation time makes the 2 h wall clock tight; measure in M4
  and adjust the iteration budget rather than the evaluation cap.
- Expectation gating adds a turn before every diagnostic. If it proves too chatty in M4, relax it
  to one expectation per diagnostic *batch* rather than per call — but never remove it, since it
  is the only defence against post-hoc rationalisation without a human reviewer.
- The expectation rule can decay in two ways, both monitored rather than prevented: unfalsifiable
  claims (guarded by the required `would_falsify` field) and self-serving grading by the model
  that made the prediction (guarded by the explicit `uninformative` verdict and the per-run
  verdict tally in `report.md`). Check both after the first real M4 run.
- SKILL.md is the source of truth and drifts (this revision renamed every tool). M1's name
  assertion catches tool renames; prompt content drift is not automatically detected.

