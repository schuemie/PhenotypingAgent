"""The `diagnose` node: turn KEEPER errors into mechanism-backed design changes."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from phenotyping_agent import stubs
from phenotyping_agent.context import base_context, design_block, keeper_block, profiles_block
from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.llm_runtime import load_prompt
from phenotyping_agent.state import AgentState, DiagnoseOutput


def _task_message(state: AgentState) -> str:
    return "\n".join(
        [
            base_context(state),
            "",
            "# Design that was evaluated",
            design_block(state.get("current_design")),
            "",
            "# KEEPER metrics",
            keeper_block(state.get("latest_keeper")),
            "",
            "# Sampled patient profiles",
            profiles_block(state.get("latest_profiles", [])),
            "",
            "# Your task",
            "Identify the failure modes, each with a mechanism, a concrete design change and the "
            "metric effect you expect from it.",
        ]
    )


def run(state: AgentState, deps: NodeDeps) -> dict:
    output = deps.runtime.structured(
        tier=deps.runtime.reasoning,
        node="diagnose",
        messages=[
            SystemMessage(content=load_prompt("diagnose")),
            HumanMessage(content=_task_message(state)),
        ],
        schema=DiagnoseOutput,
        prompt_template="diagnose",
        stub=lambda: stubs.diagnose_output(state),
        metadata={"iteration": state.get("iteration")},
    )
    assert isinstance(output, DiagnoseOutput)

    # Anti-overfitting: a change without a stated mechanism is a person-level quirk, not a fix.
    accepted = [mode for mode in output.failure_modes if mode.mechanism.strip()]

    update: dict = {"failure_modes": accepted}
    ledger = state.get("ledger", [])
    if ledger:
        amended = ledger[-1].model_copy(update={"failure_modes": accepted})
        deps.ledger_store.append(amended)
        update["ledger"] = [amended]
    return update

