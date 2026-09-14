from __future__ import annotations

from phenotyping_agent.capr_checks import validate_capr_static
from phenotyping_agent.config import AppConfig
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState


def _build_capr(state: AgentState) -> str:
    snippets = list(state["concept_set_registry"].values())
    index_set = snippets[0] if snippets else 'cs(concept(12345), name = "Acute liver failure")'
    return (
        "cohort(\n"
        "  entry = entry(conditionOccurrence(conceptSet = " + index_set + "))\n"
        ")"
    )


def run(state: AgentState, tools: ToolFacade, config: AppConfig) -> AgentState:
    capr_code = _build_capr(state)
    static_errors = validate_capr_static(capr_code, state["concept_set_registry"])
    attempts = 0
    while static_errors and attempts < config.budgets.capr_repair_attempts:
        attempts += 1
        # Minimal deterministic repair: drop fallback IDs by replacing with first known snippet.
        capr_code = _build_capr(state)
        static_errors = validate_capr_static(capr_code, state["concept_set_registry"])

    if static_errors:
        raise RuntimeError("Static Capr checks failed: " + "; ".join(static_errors))

    validation = str(tools.validate_capr(capr_code))
    if validation != "Valid":
        raise RuntimeError(f"validateCapr failed: {validation}")

    state["current_capr"] = capr_code
    return state


