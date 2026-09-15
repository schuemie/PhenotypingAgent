"""Phase 3: error-profile sampling, ledger amendment, and graceful KEEPER unavailability."""

from __future__ import annotations

from phenotyping_agent.graph import initial_state
from phenotyping_agent.nodes import diagnose, evaluate
from phenotyping_agent.nodes.evaluate import _sampling_plan
from phenotyping_agent.state import (
    Design,
    DiagnoseOutput,
    FailureMode,
    KeeperMetrics,
    LedgerEntry,
    merge_ledger,
)
from helpers import ScriptedRuntime, make_deps

DESIGN = Design(
    hypothesis="h",
    entry_event="e",
    concept_sets=[],
    inclusion_rules=[],
    exclusion_rules=[],
    temporal_logic="t",
)


def _metrics(ppv: float, sensitivity: float) -> KeeperMetrics:
    return KeeperMetrics(
        sensitivity=sensitivity, specificity=0.99, ppv=ppv, tp=1, fp=1, tn=1, fn=1
    )


def test_sampling_plan_follows_the_error_profile() -> None:
    assert _sampling_plan(_metrics(ppv=0.5, sensitivity=0.95), 6).count("FP") == 5
    assert _sampling_plan(_metrics(ppv=0.95, sensitivity=0.5), 6).count("FN") == 5
    both = _sampling_plan(_metrics(ppv=0.5, sensitivity=0.5), 6)
    assert both.count("FP") == 3 and both.count("FN") == 3
    assert len(_sampling_plan(_metrics(ppv=0.5, sensitivity=0.5), 2)) == 2


def _state():
    state = initial_state()
    state.update(
        {
            "phenotype": "Acute liver failure",
            "iteration": 1,
            "current_design": DESIGN,
            "current_cohort_id": 101,
            "ledger": [
                LedgerEntry(
                    iteration=1,
                    hypothesis="h",
                    change_from_previous="c",
                    design=DESIGN,
                    capr_code="cohort()",
                    cohort_id=101,
                    next_action="evaluate",
                )
            ],
        }
    )
    return state


def test_evaluate_amends_the_existing_ledger_entry_rather_than_duplicating_it() -> None:
    deps = make_deps("test_evaluate_amend")

    result = evaluate.run(_state(), deps)

    assert result["latest_keeper"] is not None
    merged = merge_ledger(_state()["ledger"], result["ledger"])
    assert len(merged) == 1, "the amendment must replace iteration 1, not append a second entry"
    assert merged[0].keeper is not None


def test_evaluate_stops_the_run_when_acceptance_criteria_are_met() -> None:
    deps = make_deps("test_evaluate_done")

    result = evaluate.run(_state(), deps)

    # The fixture returns ppv 0.84 / sensitivity 0.82, both above the 0.8 threshold.
    assert result["next_action"] == "done"
    assert "Acceptance criteria met" in result["stop_reason"]


def test_evaluate_reports_rather_than_crashes_when_keeper_is_unavailable() -> None:
    deps = make_deps("test_evaluate_nokeeper")

    def _boom(name, args):
        raise RuntimeError("No reference cohort for this phenotype")

    deps.tools.client.call_tool = _boom  # type: ignore[assignment]

    result = evaluate.run(_state(), deps)

    assert result["next_action"] == "done"
    assert "KEEPER evaluation is unavailable" in result["stop_reason"]


def test_evaluate_budget_is_enforced_by_the_wrapper() -> None:
    deps = make_deps("test_evaluate_budget")
    deps.tools.budget.evaluate_calls_used = deps.config.budgets.evaluate_calls

    result = evaluate.run(_state(), deps)

    assert "budget exhausted" in result["stop_reason"]


def test_diagnose_rejects_failure_modes_without_a_mechanism() -> None:
    output = DiagnoseOutput(
        summary="s",
        failure_modes=[
            FailureMode(
                pattern="kept",
                mechanism="Rule-out diagnoses are coded as confirmed in claims.",
                proposed_design_change="Require a second diagnosis.",
                expected_metric_effect="PPV up, sensitivity slightly down.",
            ),
            FailureMode(
                pattern="dropped",
                mechanism="   ",
                proposed_design_change="Exclude person 12345.",
                expected_metric_effect="PPV up.",
            ),
        ],
    )
    deps = make_deps(
        "test_diagnose", lambda config: ScriptedRuntime(config, structured=[output])
    )

    result = diagnose.run(_state(), deps)

    assert [mode.pattern for mode in result["failure_modes"]] == ["kept"]

