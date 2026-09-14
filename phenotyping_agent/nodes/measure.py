from __future__ import annotations

from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState


def run(state: AgentState, tools: ToolFacade) -> AgentState:
    cohort_id = state.get("current_cohort_id")
    if cohort_id is None:
        raise RuntimeError("No cohort ID available for diagnostics")
    counts = tools.get_cohort_count(cohort_id)
    incidence = tools.compute_incidence_rate(cohort_id)
    overlap = tools.count_concept_set_overlap(list(state["concept_set_registry"].values()), cohort_id)
    state["_counts"] = counts  # type: ignore[index]
    state["_incidence"] = incidence  # type: ignore[index]
    state["_overlap"] = overlap  # type: ignore[index]
    state["_used_expectations"] = list(tools.consumed_expectations)  # type: ignore[index]
    state["pending_expectations"] = list(tools.pending_expectations)
    return state


