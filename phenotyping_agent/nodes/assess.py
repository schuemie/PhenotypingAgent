"""The `assess` node: grade pre-registered expectations and decide the next action.

The LLM proposes `iterate | evaluate | done`; Python enforces the coded Phase 2 to Phase 3
preconditions and can override `evaluate` back to `iterate`.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from phenotyping_agent import stubs
from phenotyping_agent.context import (
    base_context,
    counts_block,
    design_block,
    expectations_block,
    incidence_block,
)
from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.llm_runtime import load_prompt
from phenotyping_agent.parsing import final_cohort_size
from phenotyping_agent.state import (
    AgentState,
    AssessOutput,
    AttritionSummary,
    Expectation,
    ExpectationVerdict,
    IncidenceSummary,
    LedgerEntry,
)


def _task_message(state: AgentState) -> str:
    return "\n".join(
        [
            base_context(state),
            "",
            "# Design under assessment",
            design_block(state.get("current_design")),
            "",
            "# Capr code",
            "```r",
            state.get("current_capr") or "",
            "```",
            "",
            "# Expectations registered BEFORE these diagnostics ran",
            expectations_block(state.get("used_expectations", [])),
            "",
            "# Cohort attrition",
            counts_block(state.get("latest_counts")),
            "",
            "# Incidence rates",
            incidence_block(state.get("latest_incidence")),
            "",
            "# Concept set overlap",
            str(state.get("latest_overlap") or "Not measured this iteration."),
            "",
            "# Your task",
            "Grade every expectation by index, interpret the results, and choose the next action.",
        ]
    )


def _gate_blockers(state: AgentState, deps: NodeDeps, output: AssessOutput) -> list[str]:
    """Coded preconditions for entering Phase 3 (plan section 5)."""
    blockers: list[str] = []
    counts = state.get("latest_counts")
    if final_cohort_size(counts) <= 0:
        blockers.append("The cohort has no members after attrition.")
    if deps.tools.call_counts.get("countConceptSetPersonOverlap", 0) < 1:
        blockers.append(
            "No countConceptSetPersonOverlap diagnostic has been run during this run; register a "
            "conceptSetOverlap expectation so the diagnostic executes."
        )
    cohort_id = state.get("current_cohort_id")
    if cohort_id is None or int(cohort_id) not in deps.tools.incidence_cohorts:
        blockers.append("computeIncidenceRate has not been run for the current cohort.")
    if not output.readiness_rationale.strip():
        blockers.append("No written readiness rationale was provided.")
    if deps.tools.budget.evaluate_calls_used >= deps.config.budgets.evaluate_calls:
        blockers.append("The KEEPER evaluation budget is already exhausted.")
    return blockers


def run(state: AgentState, deps: NodeDeps) -> dict:
    current_design = state.get("current_design")
    if current_design is None:
        raise RuntimeError("Cannot assess an iteration that has no design")
    used: list[Expectation] = list(state.get("used_expectations", []))

    output = deps.runtime.structured(
        tier=deps.runtime.reasoning,
        node="assess",
        messages=[
            SystemMessage(content=load_prompt("assess")),
            HumanMessage(content=_task_message(state)),
        ],
        schema=AssessOutput,
        prompt_template="assess",
        stub=lambda: stubs.assess_output(state),
        metadata={"iteration": state.get("iteration")},
    )
    assert isinstance(output, AssessOutput)

    verdicts = [
        ExpectationVerdict(
            expectation=used[raw.expectation_index],
            observed=raw.observed,
            verdict=raw.verdict,
            reasoning=raw.reasoning,
        )
        for raw in output.verdicts
        if 0 <= raw.expectation_index < len(used)
    ]
    graded = {raw.expectation_index for raw in output.verdicts}
    for index, expectation in enumerate(used):
        if index not in graded:
            verdicts.append(
                ExpectationVerdict(
                    expectation=expectation,
                    observed="not graded",
                    verdict="uninformative",
                    reasoning="The assessor returned no verdict for this expectation.",
                )
            )

    next_action: Literal["iterate", "evaluate", "done"] = output.next_action
    blockers: list[str] = []
    if next_action == "evaluate":
        blockers = _gate_blockers(state, deps, output)
        if blockers:
            next_action = "iterate"
    if state.get("not_expressible"):
        next_action = "done"

    entry = LedgerEntry(
        iteration=state["iteration"],
        hypothesis=current_design.hypothesis,
        change_from_previous=state.get("change_from_previous") or "",
        design=current_design,
        capr_code=state.get("current_capr") or "",
        cohort_id=state.get("current_cohort_id"),
        expectations=used,
        verdicts=verdicts,
        counts=state.get("latest_counts") or AttritionSummary(),
        incidence_rates=state.get("latest_incidence") or IncidenceSummary(),
        keeper=state.get("latest_keeper"),
        interpretation=output.interpretation,
        next_action=next_action,
        attrition_mechanisms=output.attrition_mechanisms,
        readiness_rationale=output.readiness_rationale,
        gate_blockers=blockers,
    )
    deps.ledger_store.append(entry)

    return {"ledger": [entry], "next_action": next_action, "gate_blockers": blockers}
