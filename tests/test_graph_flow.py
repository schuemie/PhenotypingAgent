"""End-to-end graph routing with scripted (LLM-shaped) node outputs.

This exercises the real `StateGraph` - including the iterate loop, the coded gate override and
the Phase 3 hand-off - without either a model or an R server.
"""

from __future__ import annotations

from phenotyping_agent.deps import BudgetGuard, NodeDeps
from phenotyping_agent.graph import build_graph, initial_state
from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import (
    AssessOutput,
    Design,
    DesignOutput,
    Expectation,
    RawVerdict,
)
from helpers import ScriptedRuntime, make_config

CAPR = 'cohort(\n  entry = entry(conditionOccurrence(conceptSet = cs(concept(12345), name = "Acute liver failure")))\n)'

DESIGN = Design(
    hypothesis="Acute liver failure is rare and severe.",
    entry_event="First ALF diagnosis.",
    concept_sets=["Acute liver failure"],
    inclusion_rules=["Adult"],
    exclusion_rules=[],
    temporal_logic="index day",
)


def _expectation(diagnostic: str) -> Expectation:
    return Expectation(
        diagnostic=diagnostic,  # type: ignore[arg-type]
        target="overall",
        claim_kind="direction",
        claim="non-zero but far smaller than all liver disease",
        would_falsify="zero members, or most of the database",
        rationale="ALF is rare.",
        basis="clinical_reasoning",
    )


def _design(change: str, with_overlap: bool) -> DesignOutput:
    diagnostics = ["cohortCount", "incidenceRate"] + (["conceptSetOverlap"] if with_overlap else [])
    return DesignOutput(
        design=DESIGN,
        change_from_previous=change,
        expectations=[_expectation(name) for name in diagnostics],
    )


def _assess(rationale: str) -> AssessOutput:
    return AssessOutput(
        verdicts=[
            RawVerdict(expectation_index=0, observed="75", verdict="held", reasoning="plausible")
        ],
        interpretation="Counts look plausible.",
        attrition_mechanisms=["Entry event only."],
        readiness_rationale=rationale,
        next_action="evaluate",
    )


def test_gate_forces_a_second_iteration_then_the_run_evaluates_and_reports() -> None:
    config = make_config("test_graph_flow")
    runtime = ScriptedRuntime(
        config,
        structured=[
            _design("Initial draft", with_overlap=False),
            _assess("Ready, in my view."),  # gate blocks: no overlap diagnostic was run
            _design("Added the overlap diagnostic", with_overlap=True),
            _assess("Overlap and incidence both checked."),
        ],
        text=[CAPR, CAPR, "Narrative."],
    )
    deps = NodeDeps(
        config=config,
        tools=ToolFacade(config),
        runtime=runtime,
        ledger_store=LedgerStore(config.runs_dir),
        budget_guard=BudgetGuard(wall_clock_minutes=config.budgets.wall_clock_minutes),
    )

    final = build_graph(deps).compile().invoke(initial_state(), config={"recursion_limit": 100})

    ledger = final["ledger"]
    assert [entry.iteration for entry in ledger] == [1, 2]

    # Iteration 1: the model asked to evaluate, the coded preconditions said no.
    assert ledger[0].next_action == "iterate"
    assert any("countConceptSetPersonOverlap" in b for b in ledger[0].gate_blockers)
    assert ledger[0].keeper is None

    # Iteration 2: preconditions met, evaluation ran, and the entry was amended in place.
    assert ledger[1].next_action == "evaluate"
    assert ledger[1].keeper is not None
    assert final["evaluate_calls"] == 1
    assert deps.tools.budget.evaluate_calls_used <= config.budgets.evaluate_calls

    assert final["next_action"] == "done"
    assert "Acceptance criteria met" in (final["stop_reason"] or "")
    assert (config.runs_dir / "report.md").exists()
    assert (config.runs_dir / "final_cohort.json").exists()


def test_a_design_that_cannot_be_expressed_skips_straight_to_the_report() -> None:
    config = make_config("test_graph_not_expressible")
    not_expressible = DesignOutput(
        design=DESIGN,
        change_from_previous="Initial draft",
        expectations=[],
        not_expressible=True,
        not_expressible_reason="Requires free-text adjudication that OMOP does not carry.",
    )
    runtime = ScriptedRuntime(config, structured=[not_expressible], text=["Narrative."])
    deps = NodeDeps(
        config=config,
        tools=ToolFacade(config),
        runtime=runtime,
        ledger_store=LedgerStore(config.runs_dir),
        budget_guard=BudgetGuard(wall_clock_minutes=config.budgets.wall_clock_minutes),
    )

    final = build_graph(deps).compile().invoke(initial_state(), config={"recursion_limit": 100})

    assert final["ledger"] == []
    assert final["current_cohort_id"] is None, "no cohort should be generated"
    report = (config.runs_dir / "report.md").read_text(encoding="utf-8")
    assert "free-text adjudication" in report

