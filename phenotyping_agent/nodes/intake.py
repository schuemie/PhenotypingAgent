from __future__ import annotations

from pathlib import Path

from phenotyping_agent.config import AppConfig
from phenotyping_agent.state import AgentState


def run(state: AgentState, config: AppConfig) -> AgentState:
    definition_path = Path(config.clinical_definition_path)
    if not definition_path.exists():
        raise FileNotFoundError(
            "Clinical definition file is required. This workflow cannot invent missing criteria."
        )
    clinical_definition = definition_path.read_text(encoding="utf-8").strip()
    phenotype = config.phenotype or clinical_definition.split(" is ")[0].strip().title()
    state["phenotype"] = phenotype
    state["clinical_definition"] = clinical_definition
    return state

