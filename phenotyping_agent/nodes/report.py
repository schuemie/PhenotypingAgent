"""The `report` node: LLM narrative plus deterministic evidence sections."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from phenotyping_agent import stubs
from phenotyping_agent.context import (
    base_context,
    counts_block,
    design_block,
    failure_modes_block,
    incidence_block,
    keeper_block,
    verdict_tally,
)
from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.ledger import render_ledger_markdown
from phenotyping_agent.llm_runtime import load_prompt
from phenotyping_agent.state import AgentState


def _tally_block(state: AgentState) -> str:
    tally = verdict_tally(state.get("ledger", []))
    total = sum(tally.values())
    if total == 0:
        return "No expectations were graded in this run."
    parts = ", ".join(f"{key}: {value}" for key, value in tally.items())
    line = f"{total} expectation verdicts - {parts}."
    if tally.get("uninformative", 0) > total / 2:
        line += (
            " More than half of the expectations were uninformative: the pre-registration gate "
            "provided little evidence in this run and the prompts need work."
        )
    return line


def _not_expressible_section(state: AgentState) -> list[str]:
    """Emitted deterministically so a model omission cannot hide a definition mismatch.

    SKILL.md rule 4: rather than shipping a silent approximation, the report must explain which
    criterion could not be expressed.
    """
    if not state.get("not_expressible"):
        return []
    return [
        "## Definition could not be fully expressed in Capr/Circe",
        state.get("not_expressible_reason")
        or "No reason was recorded, which is itself a defect worth investigating.",
        "",
        "No cohort was generated for this definition. Decompose the definition into expressible "
        "components, or capture the missing criterion outside the cohort definition, rather than "
        "treating the code below as a faithful implementation.",
        "",
    ]


def _task_message(state: AgentState) -> str:
    return "\n".join(
        [
            base_context(state),
            "",
            "# Final design",
            design_block(state.get("current_design")),
            "",
            "# Final Capr",
            "```r",
            state.get("current_capr") or "",
            "```",
            "",
            "# Final attrition",
            counts_block(state.get("latest_counts")),
            "",
            "# Final incidence",
            incidence_block(state.get("latest_incidence")),
            "",
            f"# KEEPER metrics\n{keeper_block(state.get('latest_keeper'))}",
            "",
            "# Diagnosed failure modes",
            failure_modes_block(state.get("failure_modes", [])),
            "",
            f"# Expectation verdict tally\n{_tally_block(state)}",
            "",
            "# Concept set gaps",
            ", ".join(state.get("concept_set_gaps", [])) or "None.",
            "",
            "# Why the run stopped",
            state.get("stop_reason") or f"Final action was '{state.get('next_action')}'.",
            "",
            "# Not expressible",
            state.get("not_expressible_reason")
            or ("The definition was expressible in Capr." if not state.get("not_expressible") else ""),
        ]
    )


def run(state: AgentState, deps: NodeDeps) -> dict:
    stop_reason = (
        state.get("stop_reason")
        or deps.budget_stop_reason()
        or f"Final action was '{state.get('next_action')}'."
    )
    state = {**state, "stop_reason": stop_reason}  # type: ignore[assignment]

    capr_code = state.get("current_capr") or ""
    capr_json = "{}"
    if capr_code:
        try:
            with deps.tools.restrict_to({"convertCaprToJson"}):
                capr_json = deps.tools.convert_capr_to_json(capr_code)
        except Exception as exc:  # noqa: BLE001 - never lose the report over a conversion failure
            capr_json = "{}"
            deps.runtime.event_logger.append(
                {"event": "tool_error", "node": "report", "error": str(exc)}
            )

    narrative = deps.runtime.text(
        tier=deps.runtime.fast,
        node="report",
        messages=[
            SystemMessage(content=load_prompt("report")),
            HumanMessage(content=_task_message(state)),
        ],
        prompt_template="report",
        stub=lambda: stubs.report_narrative(state),
    )

    report_text = "\n".join(
        [
            f"# Phenotyping Report: {state['phenotype']}",
            "",
            narrative.strip(),
            "",
            *_not_expressible_section(state),
            "## Final Capr",
            "```r",
            capr_code,
            "```",
            "",
            "## Final design",
            design_block(state.get("current_design")),
            "",
            "## Iteration ledger",
            render_ledger_markdown(state.get("ledger", [])),
            "",
            "## Expectation verdicts",
            _tally_block(state),
            "",
            "## Final attrition",
            counts_block(state.get("latest_counts")),
            "",
            "## Final incidence rates",
            incidence_block(state.get("latest_incidence")),
            "",
            "## KEEPER metrics",
            keeper_block(state.get("latest_keeper")),
            f"\nKEEPER evaluations used: {state.get('evaluate_calls', 0)} of "
            f"{deps.config.budgets.evaluate_calls} permitted.",
            "",
            "## Concept set gaps",
            ", ".join(state.get("concept_set_gaps", [])) or "None.",
            "",
            "## Why the run stopped",
            state.get("stop_reason") or f"Final action was '{state.get('next_action')}'.",
            "",
            "## Notes",
            "- `final_cohort.json` is written directly from `convertCaprToJson` and is, per the "
            "skill, not read back or semantically verified by the agent.",
        ]
    )

    run_dir = deps.config.runs_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.md").write_text(report_text, encoding="utf-8")
    (run_dir / "final_cohort.json").write_text(capr_json, encoding="utf-8")
    return {"final_report": report_text, "stop_reason": stop_reason}
