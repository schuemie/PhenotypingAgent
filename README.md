# Phenotyping Agent

Here you'll find a (very) experimental phenotyping agent. 
It is currently intended to be run using Github Copilot inside Visual Studio.

It has lots of dependencies you probably don't have:

- Access to a database server with patient-level data in the OMOP Common Data Model
- Access to tables containing a `KEEPER` Reference Cohort with a custom table for the patient profiles of the reference cohort.
- Access to LLMs to run `Phenelope`.
- Development version of `Phenelope` (i.e. a version that does not require providing the initial concept ID).

It also uses pre-computed concept sets.

Right now the only pre-computed data is for Acute Liver Failure.

# Example

The current example used for development:

```text
/cohort-developer #file:acute liver failure.txt 
```

# Python autonomous agent

The repository also includes a Python implementation in `phenotyping_agent/`. It follows the
workflow in `docs/LANGGRAPH_AGENT_PLAN.md` as a LangGraph state machine: LLM nodes produce
structured output for design, assessment, diagnosis and the report, while loop control,
expectation gating, the Phase 2 to Phase 3 gate and the 3-call `evaluateCohort` cap are enforced
in code. Artifacts land in `runs/<run-id>/`.

## Quick start

```powershell
python -m pip install -e .[dev]
python -m phenotyping_agent.cli list-tools --live
python -m phenotyping_agent.cli run --clinical-definition "acute liver failure.txt" --dry-run
python -m phenotyping_agent.cli run --phenotypes-csv phenotypes.csv --dry-run
python -m pytest -q
```

`--dry-run` is hermetic: it uses fixture-backed fake MCP responses *and* deterministic stand-ins
for every LLM node, so the full flow runs with no database, MCP or model connectivity.

When you pass `--phenotypes-csv`, the CLI reads each row sequentially and launches a separate run
for every phenotype in the file. Each run gets its own `runs/langgraph__<phenotype>/` folder, with
the phenotype name normalized to alphanumerics and underscores, and the CSV definition text is
written into that run directory before execution.

## Running with real models

Configure both model tiers, then run without `--dry-run`:

```powershell
python -m phenotyping_agent.cli run --phenotype "Acute liver failure" --clinical-definition "acute liver failure.txt"
```

Alternatively, you can run with a CSV of phenotypes:

```powershell
python -m phenotyping_agent.cli run --phenotypes-csv phenotypes.csv
```

Tiers can also come from `REASONING_TIER_PROVIDER` / `REASONING_TIER_MODEL` /
`FAST_TIER_PROVIDER` / `FAST_TIER_MODEL` (for example in `.env`); see `docs/LLM_CONFIGURATION.md`.
A tier left as `none` falls back to the deterministic stand-in for that node.

Optional extras: `pip install -e ".[checkpoint]"` enables SQLite checkpointing and `--resume`;
`pip install -e ".[anthropic]"` enables direct Anthropic API tiers; `pip install -e ".[bedrock]"`
enables Amazon Bedrock Claude tiers such as
`anthropic.claude-3-opus-20240229-v1:0`.

### Run artifacts

| File | Contents |
|---|---|
| `report.md` | Narrative plus ledger, metrics and the expectation-verdict tally |
| `ledger.json` | One entry per iteration: design, expectations, verdicts, counts, KEEPER |
| `llm_events.jsonl` | Every prompt, response, token usage and latency |
| `tool_calls.jsonl` | Every MCP call with arguments and result |
| `design_<n>.json`, `cohort_<n>.R` | Per-iteration design and generated Capr |
| `final_cohort.json` | `convertCaprToJson` output, written unread by design |

## Agent documentation

- Architecture and status: `docs/AGENT_HANDOFF.md`
- Runbook and troubleshooting: `docs/OPERATIONS.md`
- MCP contract details: `docs/MCP_INTEGRATION_NOTES.md`
- Guardrails for future code changes: `docs/CONTRIBUTING_AGENT.md`

