"""Deterministic stand-ins used when a model tier is configured as ``provider="none"``.

These reproduce the previous hard-coded behaviour so ``--dry-run`` stays offline, fast and
reproducible. They are never used when a real provider is configured.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from phenotyping_agent.state import (
    AgentState,
    AssessOutput,
    Design,
    DesignOutput,
    DiagnoseOutput,
    Expectation,
    FailureMode,
    RawVerdict,
)


def empty_ai_message() -> AIMessage:
    """A chat turn with no tool calls, which terminates the design tool sub-loop."""
    return AIMessage(content="")


def design_output(state: AgentState) -> DesignOutput:
    names = [c.concept_set_name for c in state["available_concept_sets"]] or [state["phenotype"]]
    design = Design(
        hypothesis=f"{state['phenotype']} should be rare and concentrated in severe acute care.",
        entry_event=f"First {state['phenotype'].lower()} diagnosis.",
        concept_sets=names,
        inclusion_rules=["Adult age >= 18 at index"],
        exclusion_rules=["Exclude pre-existing chronic liver disease"],
        temporal_logic="Require diagnosis on index and exclusions in the prior year.",
    )
    return DesignOutput(
        design=design,
        change_from_previous=(
            "Initial executable draft" if state["iteration"] <= 1 else "Stubbed iteration"
        ),
        expectations=[
            Expectation(
                diagnostic="cohortCount",
                target="overall",
                claim_kind="direction",
                claim="Non-zero and materially smaller than all-cause liver diagnoses",
                would_falsify="Zero cohort members or near-total source-population capture",
                rationale="The phenotype is rare by definition.",
                basis="clinical_reasoning",
            ),
            Expectation(
                diagnostic="incidenceRate",
                target="overall",
                claim_kind="magnitude_band",
                claim="0.01 to 1.0 events per 1,000 person-years",
                would_falsify="Incidence near zero or several events per person-year",
                rationale="A rare, severe condition should have low incidence.",
                basis="clinical_reasoning",
            ),
            Expectation(
                diagnostic="conceptSetOverlap",
                target="overall",
                claim_kind="relational",
                claim="Exclusion concept sets overlap less than index concepts around day 0",
                would_falsify="Exclusions overlap more heavily than index concepts",
                rationale="Exclusions remove secondary causes; they do not define cases.",
                basis="clinical_reasoning",
            ),
        ],
    )


def capr_code(state: AgentState) -> str:
    snippets = list(state["concept_set_registry"].values())
    index_set = snippets[0] if snippets else 'cs(concept(12345), name = "Acute liver failure")'
    return "cohort(\n  entry = entry(conditionOccurrence(conceptSet = " + index_set + "))\n)"


def assess_output(state: AgentState) -> AssessOutput:
    used = state.get("used_expectations", [])
    counts = state.get("latest_counts")
    final_count = counts.rows[-1].incremental_persons if counts and counts.rows else 0
    ready = bool(final_count and final_count > 0)
    return AssessOutput(
        verdicts=[
            RawVerdict(
                expectation_index=index,
                observed="diagnostic captured",
                verdict="uninformative",
                reasoning="Stubbed assessor records the observation without grading it.",
            )
            for index in range(len(used))
        ],
        interpretation="Counts and rates captured for the gate decision.",
        attrition_mechanisms=["Stubbed run: attrition mechanisms not analysed."],
        readiness_rationale="Non-zero cohort produced." if ready else "Cohort is empty.",
        next_action="evaluate" if ready else "iterate",
    )


def diagnose_output(state: AgentState) -> DiagnoseOutput:
    keeper = state.get("latest_keeper")
    if keeper is None:
        return DiagnoseOutput(summary="No KEEPER metrics available.")
    return DiagnoseOutput(
        summary="Stubbed diagnosis.",
        failure_modes=[
            FailureMode(
                pattern="Stubbed failure mode",
                evidence_person_count=keeper.fp + keeper.fn,
                mechanism="Stubbed run: no mechanism analysis performed.",
                proposed_design_change="No change proposed in dry-run mode.",
                expected_metric_effect="None.",
            )
        ],
    )


def report_narrative(state: AgentState) -> str:
    return (
        "This run used stubbed reasoning nodes (model provider 'none'), so the narrative below "
        "is deterministic rather than model-written.\n\n"
        f"The agent completed {len(state.get('ledger', []))} design iteration(s) for "
        f"{state['phenotype']} and stopped with action '{state.get('next_action')}'."
    )

