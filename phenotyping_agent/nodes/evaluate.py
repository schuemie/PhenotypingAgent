from __future__ import annotations

from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState, Expectation


def run(state: AgentState, tools: ToolFacade) -> AgentState:
    cohort_id = state.get("current_cohort_id")
    if cohort_id is None:
        raise RuntimeError("Cannot evaluate without cohort ID")

    tools.record_expectation(
        Expectation(
            diagnostic="keeperMetrics",
            target="overall",
            claim_kind="direction",
            claim="PPV and sensitivity should both exceed 0.8",
            would_falsify="PPV or sensitivity stays below 0.8 without clear mechanism",
            rationale="Target threshold from skill acceptance criteria.",
            basis="supplied_by_user",
        )
    )

    metrics = tools.evaluate_cohort(cohort_id, state["phenotype"])
    state["_keeper"] = metrics  # type: ignore[index]
    state["evaluate_calls"] = state.get("evaluate_calls", 0) + 1

    # Keep profile sampling deterministic by current error profile.
    for ptype in ["FP", "FP", "FP", "FN", "FN", "TP"]:
        if len(state.get("_profiles", [])) >= 6:  # type: ignore[arg-type]
            break
        profile = tools.sample_patient_profile(cohort_id, state["phenotype"], ptype)
        state.setdefault("_profiles", []).append(profile)  # type: ignore[index]

    return state

