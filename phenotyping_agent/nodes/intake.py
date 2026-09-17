from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.state import AgentState

_NAME_SYSTEM = (
    "You extract the short canonical name of the clinical phenotype described by the user's "
    "definition. Answer with the name only: no punctuation, no explanation, at most six words."
)


def _heuristic_name(clinical_definition: str) -> str:
    first_line = (
        clinical_definition.strip().splitlines()[0] if clinical_definition.strip() else ""
    )
    candidate = first_line.split(" is ")[0].strip().strip("#").strip()
    return (candidate or "Unnamed phenotype").title()


def run(state: AgentState, deps: NodeDeps) -> dict:
    """
    Load the clinical definition. Hard-fails when the definition is missing. Deriving the phenotype *name* when not
    provided.
    """
    definition_path = Path(deps.config.clinical_definition_path)
    if not definition_path.exists():
        raise FileNotFoundError(
            f"Clinical definition file not found: {definition_path}. "
            "This workflow cannot invent missing criteria."
        )
    clinical_definition = definition_path.read_text(encoding="utf-8").strip()
    if not clinical_definition:
        raise ValueError(f"Clinical definition file is empty: {definition_path}")

    phenotype = deps.config.phenotype
    if not phenotype:
        phenotype = deps.runtime.text(
            tier=deps.runtime.fast,
            node="intake",
            prompt_template="intake:phenotype_name",
            messages=[
                SystemMessage(content=_NAME_SYSTEM),
                HumanMessage(content=clinical_definition),
            ],
            stub=lambda: _heuristic_name(clinical_definition),
        ).strip().strip('"')

    return {
        "phenotype": phenotype or _heuristic_name(clinical_definition),
        "clinical_definition": clinical_definition,
    }
