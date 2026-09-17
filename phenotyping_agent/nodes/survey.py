from __future__ import annotations

from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.state import AgentState, ConceptSetSummary


def _parse_table(table_text: str) -> list[ConceptSetSummary]:
    rows = [line.strip() for line in table_text.splitlines() if line.strip().startswith("|")]
    summaries: list[ConceptSetSummary] = []
    for row in rows[2:]:
        cols = [part.strip() for part in row.strip("|").split("|")]
        if len(cols) >= 3 and cols[2].isdigit():
            summaries.append(
                ConceptSetSummary(
                    concept_set_name=cols[0],
                    with_descendants=cols[1].upper() == "Y",
                    person_count=int(cols[2]),
                )
            )
    return summaries


def run(state: AgentState, deps: NodeDeps) -> dict:
    """
    List the available concept sets and get the database description.
    """
    with deps.tools.restrict_to({"listConceptSets", "getDatabaseDescription"}):
        table = deps.tools.list_concept_sets(state["phenotype"])
        description = deps.tools.get_database_description("default")
    return {
        "available_concept_sets": _parse_table(str(table)),
        "database_description": str(description),
    }

