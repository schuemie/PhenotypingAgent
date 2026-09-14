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

# Python autonomous agent (v1 scaffold)

The repository now also includes a Python implementation scaffold in `phenotyping_agent/`.
It follows the workflow in `docs/LANGGRAPH_AGENT_PLAN.md` with deterministic loop control,
expectation gating for diagnostics, a 3-call `evaluateCohort` cap, and run artifacts in `runs/<timestamp>/`.

## Quick start

```powershell
python -m pip install -e .[dev]
python -m phenotyping_agent.cli list-tools --live
python -m phenotyping_agent.cli run --clinical-definition "acute liver failure.txt" --dry-run
python -m pytest -q
python -m phenotyping_agent.cli run --clinical-definition "acute liver failure.txt"
```

`--dry-run` uses fixture-backed fake MCP responses so the full flow runs without external database or MCP connectivity.

## Agent documentation

- Architecture and status: `docs/AGENT_HANDOFF.md`
- Runbook and troubleshooting: `docs/OPERATIONS.md`
- MCP contract details: `docs/MCP_INTEGRATION_NOTES.md`
- Guardrails for future code changes: `docs/CONTRIBUTING_AGENT.md`

