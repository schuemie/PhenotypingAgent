"""The `write_capr` repair loop: static checks, feedback, and graceful budget exhaustion."""

from __future__ import annotations

from phenotyping_agent.graph import initial_state
from phenotyping_agent.nodes import write_capr
from phenotyping_agent.state import Design
from helpers import ScriptedRuntime, make_deps

REGISTRY = {"Acute liver failure": 'cs(concept(12345), name = "Acute liver failure")'}
GOOD = 'cohort(\n  entry = entry(conditionOccurrence(conceptSet = cs(concept(12345), name = "Acute liver failure")))\n)'
HALLUCINATED_ID = 'cohort(entry = entry(conditionOccurrence(conceptSet = cs(concept(999999), name = "Made up"))))'


def _state():
    state = initial_state()
    state.update(
        {
            "phenotype": "Acute liver failure",
            "iteration": 1,
            "concept_set_registry": REGISTRY,
            "current_design": Design(
                hypothesis="h",
                entry_event="e",
                concept_sets=["Acute liver failure"],
                inclusion_rules=[],
                exclusion_rules=[],
                temporal_logic="t",
            ),
        }
    )
    return state


def _deps(run_id: str, responses: list[str]):
    return make_deps(run_id, lambda config: ScriptedRuntime(config, text=responses))


def test_hallucinated_concept_id_is_rejected_and_repaired() -> None:
    deps = _deps("test_capr_repair", [HALLUCINATED_ID, GOOD])

    result = write_capr.run(_state(), deps)

    assert result["capr_errors"] == []
    assert "12345" in (result["current_capr"] or "")
    repair_prompt = deps.runtime.messages_seen[1][-1].content  # type: ignore[attr-defined]
    assert "999999" in repair_prompt, "the static-check error must be fed back to the model"


def test_code_fences_are_stripped() -> None:
    deps = _deps("test_capr_fences", [f"```r\n{GOOD}\n```"])

    result = write_capr.run(_state(), deps)

    assert (result["current_capr"] or "").startswith("cohort(")
    assert "```" not in (result["current_capr"] or "")


def test_exhausted_repair_budget_returns_errors_instead_of_raising() -> None:
    # budgets.capr_repair_attempts == 4, so five attempts are made in total.
    deps = _deps("test_capr_exhausted", [HALLUCINATED_ID] * 5)

    result = write_capr.run(_state(), deps)

    assert result["capr_errors"], "errors must be handed back to `design`, not raised"
    assert any("999999" in error for error in result["capr_errors"])


def test_successful_code_is_written_to_an_artifact() -> None:
    deps = _deps("test_capr_artifact", [GOOD])

    write_capr.run(_state(), deps)

    assert (deps.config.runs_dir / "cohort_1.R").read_text(encoding="utf-8").startswith("cohort(")

