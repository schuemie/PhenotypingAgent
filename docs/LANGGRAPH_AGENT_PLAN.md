# Plan: Autonomous Python LangGraph Cohort-Developer Agent

Implements the workflow of `.agents/skills/cohort-developer/SKILL.md` as an unattended
Python LangGraph application, using the existing MCP tools in `tools/server.R` and the
remote `ohdsi_hecate` server. No human in the loop.

## 1. Design decisions (settled)

| # | Decision |
|---|---|
| 1 | Deterministic phase skeleton with LLM nodes producing structured output. Budgets, loops and the 3-evaluation cap are enforced in code, not by prompt compliance. |
| 2 | Nine nodes, with design (prose/spec) strictly separated from Capr code generation. |
| 3 | Structured pydantic ledger held in state, rendered into every LLM prompt. |
| 4 | Hard budgets on design iterations, Capr repairs, KEEPER evaluations, profiles, wall clock and cost. |
| 5 | `langchain-mcp-adapters` + `MultiServerMCPClient`, one long-lived `r-tools` stdio session, wrapped tools with logging/timeouts/budgets, per-node tool allow-lists. |
| 6 | Python 3.12 (uv), Azure OpenAI via the same macOS keyring entries as `server.R`, two model tiers. |
| 7 | Concept set snippets stored verbatim in a registry; static checks reject concept IDs not present in the registry. |
| 8 | SQLite checkpointer for crash tolerance / resume. **No** duplicate-design detection. |
| 9 | Phase 2 → 3 gate: a few coded preconditions plus an LLM clinical-plausibility judgement. |
| 10 | Phase 3 sampling of patient profiles is driven deterministically by the error profile; diagnoses must state a mechanism and an expected metric effect. |
| 11 | `CAPR_REFERENCE.md` read at runtime from the skill folder; per-node prompts live in the Python package. |
| 12 | v1 uses pre-computed concept sets + Hecate lookups. `createNewConceptSet` stays out of scope. |
| 13 | Six milestones, fixture-backed `--dry-run` mode, acceptance = unattended ALF run. |

## 2. Graph

```
intake → survey_concept_sets → design ⇄ (discovery tool sub-loop)
            ↓
         write_capr ⇄ (static checks + validate_capr, ≤4 repairs)
            ↓
         generate → measure → assess
            ├── iterate ──────────→ design
            ├── evaluate (gated) ─→ evaluate → diagnose → design
            └── done ─────────────→ report
```

### Nodes

1. **`intake`** (deterministic) — load the clinical definition file and phenotype name.
   Hard-fail if either is missing; the `clinical-definition-refiner` skill is interactive
   and is never invoked.
2. **`survey_concept_sets`** (deterministic) — `list_concept_sets`, `get_database_description`.
3. **`design`** (LLM, reasoning tier, structured output) — produces/revises a `Design`:
   hypothesis, entry event, concept sets *by name*, inclusion rules, temporal logic, and an
   a-priori expected incidence per 1,000 person-years. Bounded tool sub-loop with access to
   `get_concept_sets_capr`, Hecate concept lookup, `describe_measurement_values`,
   `count_concept_set_person_overlap`. Prose only — no code.
4. **`write_capr`** (LLM, fast tier) — `Design` + concept set registry + `CAPR_REFERENCE.md`
   → one `cohort(...)` expression, concept sets inlined with `name = "..."`, no assignments.
   Static checks, then `validate_capr`; ≤4 repairs, each fed the previous code and error.
   Exhaustion returns to `design` with the errors (counts as a design iteration).
5. **`generate`** (deterministic) — `generate_cohort` → cohort ID.
6. **`measure`** (deterministic) — `get_cohort_count`, `compute_incidence_rate`.
7. **`assess`** (LLM, reasoning tier, structured output) — interprets counts/attrition/incidence
   against the a-priori expectation and clinical knowledge, writes the ledger entry, returns
   `iterate | evaluate | done` with a rationale.
8. **`evaluate`** (deterministic + LLM) — `evaluate_cohort`, error-profile-driven
   `sample_patient_profile` sampling, then a `diagnose` LLM step.
9. **`report`** (LLM, fast tier) — final Capr code, ledger narrative, metrics, limitations;
   optional `convert_capr_to_json` written to file.

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
    ledger: Annotated[list[LedgerEntry], operator.add]
    budgets: Budgets
    next_action: Literal["iterate", "evaluate", "done"]
    final_report: str | None
```

### Ledger

```python
class LedgerEntry(BaseModel):
    iteration: int
    hypothesis: str
    change_from_previous: str
    design: Design
    capr_code: str
    cohort_id: int | None
    counts: AttritionSummary          # per-rule incremental / marginal / gain
    incidence_rate: float | None
    keeper: KeeperMetrics | None
    interpretation: str
    next_action: Literal["iterate", "evaluate", "done"]
```

Rendered as a markdown table plus prose into every LLM prompt, with the instruction not to
re-test changes already present. Beyond ~15 entries, older non-evaluated entries are compacted
to one line each; evaluated iterations always keep full detail.

## 4. Budgets (code-enforced)

| Budget | Value | On exhaustion |
|---|---|---|
| `design_iterations` | 8 | force transition to `evaluate` |
| `capr_repair_attempts` per design | 4 | back to `design` with validator errors |
| `evaluate_cohort` calls | **3 (hard)** | force `report` |
| `sample_patient_profile` per evaluation | 6 | — |
| wall clock | 2 h | checkpoint + report partial results |
| LLM cost/tokens | configurable | checkpoint + report partial results |

The evaluation cap is enforced by the Python tool wrapper, which raises once the budget is
spent — the model cannot burn it by accident.

Early exits: PPV and sensitivity both > 80%; or `design` declares the definition not
expressible in Capr/Circe (SKILL.md rule 4), in which case `report` explains the mismatch and
proposes a decomposition rather than shipping a silent approximation.

## 5. Phase 2 → 3 gate

Coded preconditions:

1. A cohort was generated with a non-zero final count.
2. At least one `count_concept_set_person_overlap` call has been made this run.
3. `assess` returned `next_action == "evaluate"` with a written readiness rationale.

LLM-judged plausibility (no hard thresholds — the model applies clinical and data-capture
knowledge, e.g. a rare disease must not yield millions of persons, attrition at each rule must
have a stated mechanism, and the observed incidence is compared to the a-priori expectation the
design node committed to before generation). Implausible results force another design iteration
until the 8-iteration budget forces the transition anyway.

## 6. Phase 3 details

1. `evaluate_cohort` → sensitivity, specificity, PPV, confusion matrix.
2. Deterministic profile sampling: PPV weak → 5 FP + 1 TP; sensitivity weak → 5 FN + 1 TP;
   both weak → 3 FP + 3 FN.
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
- Every tool wrapped to: log args + result to `runs/<ts>/tool_calls.jsonl`, enforce budgets,
  apply per-tool timeouts (~30 min for `generate_cohort`), retry transient connection errors once.
- Per-node allow-lists: `design` gets discovery/counting tools, `write_capr` gets only
  `validate_capr`, deterministic nodes call tools directly without an LLM.
- `--dry-run` swaps in a fake in-process MCP server backed by recorded fixtures.

## 8. Concept-ID safety

- Concept set Capr snippets enter `state["concept_set_registry"]` **verbatim** from
  `get_concept_sets_capr` / Hecate; the design node refers to sets by name only.
- Before calling `validate_capr`, a Python static check asserts:
  - every integer concept ID in the emitted code appears in a registry snippet;
  - exactly one top-level `cohort(` call;
  - no top-level assignments.
- Violations are returned as repair feedback — cheaper and more specific than the R validator.
- Missing concept sets are recorded as a `concept_set_gap` in the ledger and flagged in the
  final report; `create_new_concept_set` remains disabled in v1.

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
  config.py                    # models, budgets, paths, mcp.json location
  state.py                     # TypedDict + pydantic models
  graph.py                     # StateGraph, conditional edges, checkpointer
  nodes/                       # intake, survey, design, write_capr, generate, measure, assess, evaluate, report
  mcp_tools.py                 # MultiServerMCPClient, wrappers, budgets, logging, allow-lists
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
`report`. Model IDs in `config.yaml`.

## 11. Milestones

- **M1 Plumbing** — py3.12 venv, deps, `mcp_tools.py`, a `list-tools` CLI command proving stdio
  wiring and Azure credentials before any graph exists.
- **M2 Fixtures** — record real responses for ALF (`list_concept_sets`, `get_concept_sets_capr`,
  `validate_capr`, `get_cohort_count`, `evaluate_cohort`); build the fake MCP server for `--dry-run`.
- **M3 Codegen path** — `design` → `write_capr` → static checks → `validate_capr`, tested
  standalone against a hand-written ALF design. Highest-risk node, proven early.
- **M4 Phase 2 loop** — generate/measure/assess, ledger, budgets, checkpointer; end-to-end ALF run
  without touching `evaluate_cohort`.
- **M5 Phase 3** — evaluation, profile sampling, diagnose, hard 3-call cap; full autonomous run.
- **M6 Report and polish** — `report.md`, `convert_capr_to_json` output, README section.

**Acceptance for v1:** an unattended
`python -m phenotyping_agent --clinical-definition "acute liver failure.txt"` run completes,
produces a valid Capr definition, a coherent ledger, at most 3 KEEPER evaluations, and
PPV/sensitivity at least comparable to the current Copilot-driven skill.

## 12. Open risks

- Phase 3 requires the reference cohort; `getKeeperReferenceCohortId` currently only supports
  Acute Liver Failure, so other phenotypes stop after Phase 2. The agent should detect this and
  report it rather than fail.
- Single-threaded R MCP server: any long Databricks call blocks the whole run; timeouts must be
  generous and the wrapper must not silently retry a cohort generation.
- Reasoning-model latency plus cohort generation time makes the 2 h wall clock tight; measure in M4
  and adjust the iteration budget rather than the evaluation cap.
```
