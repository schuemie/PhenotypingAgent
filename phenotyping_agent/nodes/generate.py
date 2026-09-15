from __future__ import annotations

from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.state import AgentState


def run(state: AgentState, deps: NodeDeps) -> dict:
    capr = state.get("current_capr")
    if not capr:
        raise RuntimeError("No Capr code available to generate a cohort from")
    with deps.tools.restrict_to({"generateCohort"}):
        cohort_id = deps.tools.generate_cohort(capr)
    return {"current_cohort_id": cohort_id}
