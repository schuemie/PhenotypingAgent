"""The Phase 2 to Phase 3 gate: coded preconditions can override the model's `evaluate`."""

from __future__ import annotations

from phenotyping_agent.graph import initial_state
from phenotyping_agent.nodes import assess
from phenotyping_agent.state import (
    AssessOutput,
    AttritionRow,
    AttritionSummary,
    Design,
    Expectation,
    RawVerdict,
)
from helpers import ScriptedRuntime, make_deps

DESIGN = Design(
    hypothesis="h",
    entry_event="e",
    concept_sets=["Acute liver failure"],
    inclusion_rules=[],
    exclusion_rules=[],
    temporal_logic="t",
)

EXPECTATION = Expectation(
    diagnostic="cohortCount",
    target="overall",
    claim_kind="direction",
    claim="Non-zero",
    would_falsify="Count is zero",
    rationale="r",
    basis="clinical_reasoning",
)


def _state(**overrides):
    state = initial_state()
    state.update(
        {
            "phenotype": "Acute liver failure",
            "clinical_definition": "def",
            "iteration": 1,
            "current_design": DESIGN,
            "current_capr": "cohort()",
            "current_cohort_id": 101,
            "used_expectations": [EXPECTATION],
            "latest_counts": AttritionSummary(
                rows=[AttritionRow(rule_sequence=0, name="Initial event", incremental_persons=75)]
            ),
        }
    )
    state.update(overrides)
    return state


def _output(**overrides) -> AssessOutput:
    payload = {
        "verdicts": [
            RawVerdict(
                expectation_index=0, observed="75", verdict="held", reasoning="non-zero and small"
            )
        ],
        "interpretation": "plausible",
        "readiness_rationale": "Counts and rates look right.",
        "next_action": "evaluate",
    }
    payload.update(overrides)
    return AssessOutput(**payload)


def _deps(run_id: str, output: AssessOutput):
    return make_deps(run_id, lambda config: ScriptedRuntime(config, structured=[output]))


def test_gate_blocks_evaluate_without_the_required_diagnostics() -> None:
    deps = _deps("test_gate_blocked", _output())

    result = assess.run(_state(), deps)

    assert result["next_action"] == "iterate", "no overlap/incidence call was made this run"
    blockers = result["gate_blockers"]
    assert any("countConceptSetPersonOverlap" in b for b in blockers)
    assert any("computeIncidenceRate" in b for b in blockers)


def test_gate_allows_evaluate_once_preconditions_are_met() -> None:
    deps = _deps("test_gate_open", _output())
    deps.tools.call_counts["countConceptSetPersonOverlap"] = 1
    deps.tools.incidence_cohorts.add(101)

    result = assess.run(_state(), deps)

    assert result["next_action"] == "evaluate"
    assert result["gate_blockers"] == []


def test_gate_blocks_an_empty_cohort_and_a_missing_rationale() -> None:
    deps = _deps("test_gate_empty", _output(readiness_rationale="   "))
    deps.tools.call_counts["countConceptSetPersonOverlap"] = 1
    deps.tools.incidence_cohorts.add(101)
    empty = AttritionSummary(
        rows=[AttritionRow(rule_sequence=0, name="Initial event", incremental_persons=0)]
    )

    result = assess.run(_state(latest_counts=empty), deps)

    assert result["next_action"] == "iterate"
    assert any("no members" in b for b in result["gate_blockers"])
    assert any("readiness rationale" in b for b in result["gate_blockers"])


def test_ungraded_expectations_are_recorded_as_uninformative() -> None:
    deps = _deps("test_gate_ungraded", _output(verdicts=[]))

    result = assess.run(_state(), deps)

    entry = result["ledger"][0]
    assert len(entry.verdicts) == 1
    assert entry.verdicts[0].verdict == "uninformative"

