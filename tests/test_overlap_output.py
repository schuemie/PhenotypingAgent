"""Compact concept-set overlap output across the MCP/Python boundary."""

from __future__ import annotations

from phenotyping_agent.context import overlap_block
from phenotyping_agent.graph import initial_state
from phenotyping_agent.nodes import assess, measure
from phenotyping_agent.state import Design, Expectation
from helpers import make_deps


def _expectation(diagnostic: str) -> Expectation:
    return Expectation(
        diagnostic=diagnostic,  # type: ignore[arg-type]
        target="overall",
        claim_kind="relational",
        claim=f"A registered {diagnostic} relationship will be observed.",
        would_falsify=f"The registered {diagnostic} relationship is not observed.",
        rationale="Exercises diagnostic gating.",
        basis="clinical_reasoning",
    )


def test_overlap_block_preserves_markdown_table_verbatim() -> None:
    table = "| conceptSetName | overallPersons |\n| --- | --- |\n| A \\| B | 12 |"

    assert overlap_block(table) == table


def test_overlap_block_supports_legacy_rows_and_empty_results() -> None:
    rows = [{"conceptSetName": "A", "overallPersons": 12}]

    assert "conceptSetName" in overlap_block(rows)
    assert overlap_block([]) == "Not measured this iteration."
    assert overlap_block(None) == "Not measured this iteration."


def test_measure_preserves_mcp_overlap_table_for_assessment() -> None:
    deps = make_deps("test_overlap_markdown")
    for diagnostic in ("cohortCount", "incidenceRate", "conceptSetOverlap"):
        deps.tools.record_expectation(_expectation(diagnostic))

    state = initial_state()
    state.update(
        {
            "current_cohort_id": 101,
            "current_design": Design(
                hypothesis="Acute liver failure is rare.",
                entry_event="First diagnosis.",
                concept_sets=["Acute liver failure", "Stale exploratory set"],
                overlap_concept_sets=["Acute liver failure"],
                temporal_logic="Index day.",
            ),
            "concept_set_registry": {
                "Acute liver failure": 'cs(concept(12345), name = "Acute liver failure")',
                "Stale exploratory set": 'cs(concept(99999), name = "Stale exploratory set")',
            },
        }
    )

    update = measure.run(state, deps)

    assert isinstance(update["latest_overlap"], str)
    assert update["latest_overlap"].startswith("| conceptSetName |")
    state.update(update)  # type: ignore[typeddict-item]
    task = assess._task_message(state)
    assert update["latest_overlap"] in task
    assert "['| conceptSetName" not in task

    calls = deps.tools.log_path.read_text(encoding="utf-8").splitlines()
    overlap_call = next(line for line in reversed(calls) if '"countConceptSetPersonOverlap"' in line)
    assert "concept(12345)" in overlap_call
    assert "concept(99999)" not in overlap_call

