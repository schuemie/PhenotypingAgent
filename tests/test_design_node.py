"""The `design` node: expectation pre-registration, tool sub-loop and concept-set safety."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from phenotyping_agent.graph import initial_state
from phenotyping_agent.nodes import design
from phenotyping_agent.state import (
    ConceptSetSummary,
    Design,
    DesignOutput,
    Expectation,
)
from helpers import ScriptedRuntime, make_deps

DESIGN = Design(
    hypothesis="Acute liver failure is rare.",
    entry_event="First diagnosis.",
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
        claim="non-zero but small",
        would_falsify="zero members",
        rationale="rare disease",
        basis="clinical_reasoning",
    )


def _state():
    state = initial_state()
    state.update(
        {
            "phenotype": "Acute liver failure",
            "clinical_definition": "ALF is ...",
            "database_description": "claims",
            "available_concept_sets": [
                ConceptSetSummary(
                    concept_set_name="Acute liver failure", with_descendants=True, person_count=100
                )
            ],
        }
    )
    return state


def _deps(run_id: str, outputs: list[DesignOutput], chat: list | None = None):
    return make_deps(
        run_id,
        lambda config: ScriptedRuntime(
            config, structured=outputs, chat=chat or [AIMessage(content="")]
        ),
    )


def test_design_registers_required_expectations_and_increments_the_iteration() -> None:
    output = DesignOutput(
        design=DESIGN,
        change_from_previous="Initial draft",
        expectations=[_expectation("cohortCount"), _expectation("incidenceRate")],
    )
    deps = _deps("test_design_ok", [output])

    result = design.run(_state(), deps)

    assert result["iteration"] == 1
    registered = {(e.diagnostic, e.target) for e in result["pending_expectations"]}
    assert ("cohortCount", "overall") in registered
    assert ("incidenceRate", "overall") in registered
    assert (deps.config.runs_dir / "design_1.json").exists()


def test_missing_expectations_trigger_exactly_one_repair_turn() -> None:
    incomplete = DesignOutput(
        design=DESIGN, change_from_previous="x", expectations=[_expectation("cohortCount")]
    )
    complete = DesignOutput(
        design=DESIGN,
        change_from_previous="x",
        expectations=[_expectation("cohortCount"), _expectation("incidenceRate")],
    )
    deps = _deps("test_design_repair", [incomplete, complete])

    result = design.run(_state(), deps)

    structured_calls = [call for call in deps.runtime.calls if call[0] == "structured"]  # type: ignore[attr-defined]
    assert len(structured_calls) == 2
    repair_prompt = deps.runtime.messages_seen[-1][-1].content  # type: ignore[attr-defined]
    assert "incidenceRate" in repair_prompt
    assert len(result["pending_expectations"]) == 2


def test_design_fails_loudly_when_gating_would_block_the_run() -> None:
    incomplete = DesignOutput(
        design=DESIGN, change_from_previous="x", expectations=[_expectation("cohortCount")]
    )
    deps = _deps("test_design_fail", [incomplete, incomplete])

    with pytest.raises(RuntimeError, match="required expectations"):
        design.run(_state(), deps)


def test_named_concept_sets_are_resolved_into_the_registry_verbatim() -> None:
    output = DesignOutput(
        design=DESIGN,
        change_from_previous="x",
        expectations=[_expectation("cohortCount"), _expectation("incidenceRate")],
    )
    deps = _deps("test_design_registry", [output])

    result = design.run(_state(), deps)

    registry = result["concept_set_registry"]
    assert registry, "the design node must resolve concept sets before write_capr runs"
    assert all("cs(" in snippet for snippet in registry.values())


def test_tool_sub_loop_executes_tool_calls_and_feeds_results_back() -> None:
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "getConceptSetsCapr",
                "args": {"conceptSetNames": ["Acute liver failure"]},
                "id": "call_1",
            }
        ],
    )
    output = DesignOutput(
        design=DESIGN,
        change_from_previous="x",
        expectations=[_expectation("cohortCount"), _expectation("incidenceRate")],
    )
    deps = _deps("test_design_tools", [output], chat=[call, AIMessage(content="done")])

    design.run(_state(), deps)

    assert deps.tools.call_counts["getConceptSetsCapr"] >= 1
    tool_messages = [m for m in deps.runtime.messages_seen[-1] if m.type == "tool"]  # type: ignore[attr-defined]
    assert tool_messages and "cs(" in tool_messages[0].content


def test_unknown_tool_errors_are_returned_to_the_model_not_raised() -> None:
    call = AIMessage(
        content="", tool_calls=[{"name": "notATool", "args": {}, "id": "call_1"}]
    )
    output = DesignOutput(
        design=DESIGN,
        change_from_previous="x",
        expectations=[_expectation("cohortCount"), _expectation("incidenceRate")],
    )
    deps = _deps("test_design_toolerr", [output], chat=[call, AIMessage(content="ok")])

    design.run(_state(), deps)

    tool_messages = [m for m in deps.runtime.messages_seen[-1] if m.type == "tool"]  # type: ignore[attr-defined]
    assert tool_messages and tool_messages[0].content.startswith("ERROR:")

