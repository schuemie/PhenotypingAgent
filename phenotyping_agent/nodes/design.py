"""The `design` node: an LLM reasoning step with a bounded diagnostic tool sub-loop.

Produces prose only. Concept sets are referred to by name; their Capr snippets enter the
registry verbatim from `getConceptSetsCapr` so the static concept-ID check has an authoritative
allow-list.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from phenotyping_agent import stubs
from phenotyping_agent.context import EXPECTATION_RULES, base_context, design_block, failure_modes_block
from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.llm_runtime import load_prompt
from phenotyping_agent.state import AgentState, DesignOutput, Expectation

MAX_TOOL_TURNS = 6
DESIGN_TOOL_ALLOWLIST = {
    "getConceptSetsCapr",
    "describeMeasurementValues",
    "countConceptSetPersonOverlap",
}
REQUIRED_DIAGNOSTICS = ("cohortCount", "incidenceRate")


class _RecordExpectationArgs(BaseModel):
    diagnostic: Literal[
        "cohortCount", "incidenceRate", "conceptSetOverlap", "measurementValues", "keeperMetrics"
    ]
    target: str = Field(default="overall", description="Concept set name, stratum, or 'overall'.")
    claim_kind: Literal["relational", "magnitude_band", "direction"]
    claim: str
    would_falsify: str
    rationale: str
    basis: Literal["clinical_reasoning", "supplied_by_user", "retrieved_from_source"] = (
        "clinical_reasoning"
    )
    source: str | None = None


class _ConceptSetNames(BaseModel):
    conceptSetNames: list[str] = Field(description="Concept set names exactly as listed.")


class _MeasurementArgs(BaseModel):
    conceptSetNames: list[str]
    target: str = Field(
        default="overall",
        description="Must match the `target` of the registered measurementValues expectation.",
    )


def _build_tools(state: AgentState, deps: NodeDeps, registry: dict[str, str], gaps: list[str]) -> list[Any]:
    facade = deps.tools

    def record_expectation(
        diagnostic: str,
        claim_kind: str,
        claim: str,
        would_falsify: str,
        rationale: str,
        target: str = "overall",
        basis: str = "clinical_reasoning",
        source: str | None = None,
    ) -> str:
        expectation = Expectation(
            diagnostic=diagnostic,  # type: ignore[arg-type]
            target=target,
            claim_kind=claim_kind,  # type: ignore[arg-type]
            claim=claim,
            would_falsify=would_falsify,
            rationale=rationale,
            basis=basis,  # type: ignore[arg-type]
            source=source,
        )
        facade.record_expectation(expectation)
        return f"Registered expectation for {expectation.diagnostic}/{expectation.target}."

    def get_concept_sets_capr(conceptSetNames: list[str]) -> str:
        fetched, missing = facade.fetch_concept_set_snippets(state["phenotype"], conceptSetNames)
        registry.update(fetched)
        for name in missing:
            if name not in gaps:
                gaps.append(name)
        lines = [f"{name}:\n{code}" for name, code in fetched.items()]
        if missing:
            lines.append(
                "NOT FOUND (recorded as a concept-set gap; do not use these): " + ", ".join(missing)
            )
        return "\n\n".join(lines) or "No concept sets returned."

    def describe_measurement_values(conceptSetNames: list[str], target: str = "overall") -> str:
        snippets = [registry[name] for name in conceptSetNames if name in registry]
        if not snippets:
            return "Call getConceptSetsCapr for these concept sets first."
        return json.dumps(facade.describe_measurements(snippets, target), default=str)[:4000]

    def count_concept_set_person_overlap(conceptSetNames: list[str]) -> str:
        cohort_id = state.get("current_cohort_id")
        if cohort_id is None:
            return "No cohort has been generated yet, so overlap cannot be computed."
        snippets = [registry[name] for name in conceptSetNames if name in registry]
        if not snippets:
            return "Call getConceptSetsCapr for these concept sets first."
        return json.dumps(facade.count_concept_set_overlap(snippets, cohort_id), default=str)[:4000]

    return [
        StructuredTool.from_function(
            func=record_expectation,
            name="recordExpectation",
            description="Pre-register an expectation. Required before any gated diagnostic runs.",
            args_schema=_RecordExpectationArgs,
        ),
        StructuredTool.from_function(
            func=get_concept_sets_capr,
            name="getConceptSetsCapr",
            description="Fetch verbatim Capr snippets and counts for named pre-computed concept sets.",
            args_schema=_ConceptSetNames,
        ),
        StructuredTool.from_function(
            func=describe_measurement_values,
            name="describeMeasurementValues",
            description=(
                "Units and value distributions for measurement concept sets. Gated: register a "
                "measurementValues expectation with a matching target first."
            ),
            args_schema=_MeasurementArgs,
        ),
        StructuredTool.from_function(
            func=count_concept_set_person_overlap,
            name="countConceptSetPersonOverlap",
            description=(
                "How many people in the current cohort also have the given concept sets. Gated: "
                "register a conceptSetOverlap expectation first."
            ),
            args_schema=_ConceptSetNames,
        ),
    ]


def _task_message(state: AgentState) -> str:
    sections = [
        base_context(state),
        "",
        "# Current design (to be revised)",
        design_block(state.get("current_design")),
        "",
        "# Failure modes diagnosed from the last evaluation",
        failure_modes_block(state.get("failure_modes", [])),
    ]
    capr_errors = state.get("capr_errors", [])
    if capr_errors:
        sections += [
            "",
            "# The previous design could not be expressed in valid Capr",
            "The code generator exhausted its repair budget with these errors. Adjust the design "
            "so it can be expressed, or set not_expressible=true:",
            *[f"- {error}" for error in capr_errors],
        ]
    sections += [
        "",
        "# Your task",
        "Investigate with the tools as needed, then produce the design and its expectations.",
    ]
    return "\n".join(sections)


def _missing_required(expectations: list[Expectation]) -> list[str]:
    present = {(e.diagnostic, e.target) for e in expectations}
    return [name for name in REQUIRED_DIAGNOSTICS if (name, "overall") not in present]


def run(state: AgentState, deps: NodeDeps) -> dict:
    iteration = int(state.get("iteration", 0)) + 1
    stub_state = cast(AgentState, {**state, "iteration": iteration})
    facade = deps.tools
    facade.reset_expectations()

    registry: dict[str, str] = dict(state.get("concept_set_registry") or {})
    gaps: list[str] = list(state.get("concept_set_gaps") or [])

    system = SystemMessage(
        content=load_prompt("design").replace("{expectation_rules}", EXPECTATION_RULES)
    )
    messages: list[Any] = [system, HumanMessage(content=_task_message(state))]

    # ---------------------------------------------------------- tool sub-loop
    tool_defs = _build_tools(state, deps, registry, gaps)
    tools_by_name = {tool.name: tool for tool in tool_defs}
    with facade.restrict_to(DESIGN_TOOL_ALLOWLIST):
        for _ in range(MAX_TOOL_TURNS):
            ai = deps.runtime.chat(
                tier=deps.runtime.reasoning,
                node="design",
                messages=messages,
                tools=tool_defs,
                prompt_template="design",
                stub=stubs.empty_ai_message,
                metadata={"iteration": iteration, "phase": "explore"},
            )
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None) or []
            if not calls:
                break
            for call in calls:
                tool = tools_by_name.get(call["name"])
                try:
                    if tool is None:
                        raise RuntimeError(f"Unknown tool '{call['name']}'")
                    observation = tool.invoke(call["args"])
                except Exception as exc:  # noqa: BLE001 - surfaced to the model for self-repair
                    observation = f"ERROR: {exc}"
                messages.append(
                    ToolMessage(content=str(observation), tool_call_id=call["id"])
                )

    # ------------------------------------------------------- structured emit
    messages.append(
        HumanMessage(
            content=(
                "Now return the final DesignOutput. Refer to concept sets by name only and "
                "include the required expectations for cohortCount/overall and "
                "incidenceRate/overall."
            )
        )
    )
    output = deps.runtime.structured(
        tier=deps.runtime.reasoning,
        node="design",
        messages=messages,
        schema=DesignOutput,
        prompt_template="design",
        stub=lambda: stubs.design_output(stub_state),
        metadata={"iteration": iteration, "phase": "emit"},
    )
    assert isinstance(output, DesignOutput)

    missing = _missing_required(output.expectations)
    if missing and not output.not_expressible:
        messages += [
            AIMessage(content=output.model_dump_json()),
            HumanMessage(
                content=(
                    "Expectation gating will block the run: no expectation was registered for "
                    f"{', '.join(missing)} with target 'overall'. Return the DesignOutput again "
                    "with those expectations added."
                )
            ),
        ]
        output = deps.runtime.structured(
            tier=deps.runtime.reasoning,
            node="design",
            messages=messages,
            schema=DesignOutput,
            prompt_template="design",
            stub=lambda: stubs.design_output(stub_state),
            metadata={"iteration": iteration, "phase": "expectation_repair"},
        )
        assert isinstance(output, DesignOutput)

    # Deterministic safety net: every named concept set must be in the registry verbatim before
    # write_capr can inline it.
    unresolved = [name for name in output.design.concept_sets if name not in registry]
    if unresolved:
        with facade.restrict_to({"getConceptSetsCapr"}):
            fetched, missing_sets = facade.fetch_concept_set_snippets(state["phenotype"], unresolved)
        registry.update(fetched)
        for name in missing_sets:
            if name not in gaps:
                gaps.append(name)

    for expectation in output.expectations:
        facade.record_expectation(expectation)

    still_missing = _missing_required(list(facade.pending_expectations))
    if still_missing and not output.not_expressible:
        raise RuntimeError(
            "Design failed to pre-register required expectations for: "
            + ", ".join(still_missing)
        )

    design_path = deps.config.runs_dir / f"design_{iteration}.json"
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")

    return {
        "iteration": iteration,
        "current_design": output.design,
        "concept_set_registry": registry,
        "concept_set_gaps": gaps,
        "pending_expectations": list(facade.pending_expectations),
        "change_from_previous": output.change_from_previous,
        "not_expressible": output.not_expressible,
        "not_expressible_reason": output.not_expressible_reason,
        "capr_errors": [],
        "failure_modes": [],
    }
