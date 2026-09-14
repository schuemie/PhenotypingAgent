from __future__ import annotations

from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState, Design, Expectation


def run(state: AgentState, tools: ToolFacade) -> AgentState:
    concept_names = [c.concept_set_name for c in state["available_concept_sets"][:3]]
    if not concept_names:
        concept_names = ["Acute liver failure"]

    state["current_design"] = Design(
        hypothesis="Acute liver failure should be rare and concentrated in severe acute care.",
        entry_event="First acute liver failure diagnosis.",
        concept_sets=concept_names,
        inclusion_rules=["Adult age >= 18 at index", "Exclude pre-existing chronic liver disease"],
        exclusion_rules=["Exclude secondary shock liver causes"],
        temporal_logic="Require diagnosis on index and exclusions in prior year.",
    )

    snippets = tools.get_concept_sets_capr(state["phenotype"], concept_names, detail="code_and_counts")
    registry: dict[str, str] = {}
    if isinstance(snippets, list):
        for idx, row in enumerate(snippets):
            name = concept_names[idx] if idx < len(concept_names) else f"concept_set_{idx}"
            registry[name] = str(row.get("capr", ""))
    state["concept_set_registry"] = registry

    tools.record_expectation(
        Expectation(
            diagnostic="cohortCount",
            target="overall",
            claim_kind="direction",
            claim="Non-zero and materially smaller than all-cause liver diagnoses",
            would_falsify="Zero cohort members or near-total source-population capture",
            rationale="ALF is rare by definition.",
            basis="clinical_reasoning",
        )
    )
    tools.record_expectation(
        Expectation(
            diagnostic="incidenceRate",
            target="overall",
            claim_kind="magnitude_band",
            claim="0.01 to 1.0 events per 1,000 person-years",
            would_falsify="Incidence near zero or several events per person-year",
            rationale="A rare, severe condition should have low incidence.",
            basis="clinical_reasoning",
        )
    )
    tools.record_expectation(
        Expectation(
            diagnostic="conceptSetOverlap",
            target="overall",
            claim_kind="relational",
            claim="Exclusion concept sets should overlap less than index concepts around day 0",
            would_falsify="Exclusions overlap more heavily than index concepts",
            rationale="Exclusions are intended to remove secondary causes, not define cases.",
            basis="clinical_reasoning",
        )
    )
    state["pending_expectations"] = list(tools.pending_expectations)
    return state


