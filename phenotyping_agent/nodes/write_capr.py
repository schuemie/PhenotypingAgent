"""The `write_capr` node: translate the design into one valid Capr expression.

Repairs are bounded; on exhaustion the errors are handed back to `design` rather than crashing
the run, which counts as a design iteration.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from phenotyping_agent import stubs
from phenotyping_agent.capr_checks import validate_capr_static
from phenotyping_agent.context import design_block
from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.llm_runtime import load_prompt
from phenotyping_agent.parsing import strip_code_fences
from phenotyping_agent.state import AgentState


def _capr_reference(deps: NodeDeps, max_chars: int = 24000) -> str:
    path = deps.config.capr_reference_path
    if not path.exists():
        return "CAPR_REFERENCE.md is not available; rely on your knowledge of the Capr API."
    return path.read_text(encoding="utf-8")[:max_chars]


def _task_message(state: AgentState, deps: NodeDeps) -> str:
    registry = state.get("concept_set_registry") or {}
    snippets = "\n\n".join(f"## {name}\n```r\n{code}\n```" for name, code in registry.items())
    return "\n".join(
        [
            "# Capr reference",
            _capr_reference(deps),
            "",
            "# Concept set registry (inline these verbatim)",
            snippets or "The registry is empty.",
            "",
            "# Design to express",
            design_block(state.get("current_design")),
            "",
            "Return the Capr code only.",
        ]
    )


def run(state: AgentState, deps: NodeDeps) -> dict:
    system = SystemMessage(content=load_prompt("write_capr"))
    messages: list[Any] = [system, HumanMessage(content=_task_message(state, deps))]
    registry = state.get("concept_set_registry") or {}

    errors: list[str] = []
    capr_code = ""
    attempts = deps.config.budgets.capr_repair_attempts

    with deps.tools.restrict_to({"validateCapr"}):
        for attempt in range(attempts + 1):
            capr_code = strip_code_fences(
                deps.runtime.text(
                    tier=deps.runtime.fast,
                    node="write_capr",
                    messages=messages,
                    prompt_template="write_capr",
                    stub=lambda: stubs.capr_code(state),
                    metadata={"iteration": state.get("iteration"), "attempt": attempt},
                )
            )

            errors = validate_capr_static(capr_code, registry)
            if not errors:
                validation = str(deps.tools.validate_capr(capr_code)).strip()
                if validation.lower() == "valid":
                    iteration = state.get("iteration", 0)
                    path = deps.config.runs_dir / f"cohort_{iteration}.R"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(capr_code, encoding="utf-8")
                    return {"current_capr": capr_code, "capr_errors": []}
                errors = [f"validateCapr reported: {validation}"]

            if attempt == attempts:
                break
            messages += [
                AIMessage(content=capr_code),
                HumanMessage(
                    content=(
                        "That code was rejected:\n"
                        + "\n".join(f"- {error}" for error in errors)
                        + "\nReturn corrected Capr code only."
                    )
                ),
            ]

    # Repair budget exhausted: hand the errors back to `design`.
    return {"current_capr": capr_code or None, "capr_errors": errors}
