from __future__ import annotations

from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState


def run(state: AgentState, tools: ToolFacade) -> AgentState:
    capr = state.get("current_capr")
    if not capr:
        raise RuntimeError("No Capr code available")
    state["current_cohort_id"] = tools.generate_cohort(capr)
    return state

