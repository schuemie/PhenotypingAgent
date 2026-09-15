"""The `measure` node: run the Phase 2 diagnostics that `design` pre-registered expectations for."""

from __future__ import annotations

from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.parsing import parse_attrition, parse_incidence
from phenotyping_agent.state import AgentState

MEASURE_TOOL_ALLOWLIST = {
    "getCohortCount",
    "computeIncidenceRate",
    "countConceptSetPersonOverlap",
}


def run(state: AgentState, deps: NodeDeps) -> dict:
    cohort_id = state.get("current_cohort_id")
    if cohort_id is None:
        raise RuntimeError("No cohort ID available for diagnostics")

    facade = deps.tools
    overlap: list = []
    with facade.restrict_to(MEASURE_TOOL_ALLOWLIST):
        counts = parse_attrition(facade.get_cohort_count(cohort_id))
        incidence = parse_incidence(facade.compute_incidence_rate(cohort_id))
        # Only run when `design` chose to pre-register it; the gate keeps the pressure on.
        if facade.has_pending("conceptSetOverlap", "overall"):
            snippets = list((state.get("concept_set_registry") or {}).values())
            if snippets:
                raw = facade.count_concept_set_overlap(snippets, cohort_id)
                overlap = raw if isinstance(raw, list) else [raw]

    return {
        "latest_counts": counts,
        "latest_incidence": incidence,
        "latest_overlap": overlap,
        "used_expectations": list(facade.consumed_expectations),
        "pending_expectations": list(facade.pending_expectations),
    }
