"""LangGraph wiring for the cohort-developer agent.

```
intake -> survey -> design -> write_capr -> generate -> measure -> assess
                      ^           |                                  |
                      |  (capr repair budget exhausted)              |
                      |                                              +-- iterate --> design
                      +-- diagnose <-- evaluate <-- (gated) ---------+-- evaluate
                                                                     +-- done ----> report
```

Budgets, the loop structure and the three-evaluation cap live here in code, not in prompts.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from phenotyping_agent.config import AppConfig
from phenotyping_agent.deps import BudgetGuard, NodeDeps
from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.llm_events import LLMEventLogger
from phenotyping_agent.llm_runtime import LLMRuntime
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.nodes import (
    assess,
    design,
    diagnose,
    evaluate,
    generate,
    intake,
    measure,
    report,
    survey,
    write_capr,
)
from phenotyping_agent.parsing import final_cohort_size
from phenotyping_agent.state import AgentState

RECURSION_LIMIT = 250


def initial_state() -> AgentState:
    return {
        "phenotype": "",
        "clinical_definition": "",
        "database_description": "",
        "available_concept_sets": [],
        "concept_set_registry": {},
        "current_design": None,
        "current_capr": None,
        "current_cohort_id": None,
        "pending_expectations": [],
        "used_expectations": [],
        "ledger": [],
        "next_action": "iterate",
        "final_report": None,
        "iteration": 0,
        "evaluate_calls": 0,
        "latest_counts": None,
        "latest_incidence": None,
        "latest_overlap": [],
        "latest_measurements": [],
        "latest_keeper": None,
        "latest_profiles": [],
        "change_from_previous": "",
        "capr_errors": [],
        "failure_modes": [],
        "concept_set_gaps": [],
        "not_expressible": False,
        "not_expressible_reason": None,
        "stop_reason": None,
        "gate_blockers": [],
    }


def _make_checkpointer(config: AppConfig) -> Any:
    """SQLite checkpointing when `langgraph-checkpoint-sqlite` is installed, else none."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore import-not-found
    except ImportError:
        return None
    config.runs_dir.mkdir(parents=True, exist_ok=True)
    import sqlite3

    connection = sqlite3.connect(
        str(config.runs_dir / "checkpoint.db"), check_same_thread=False
    )
    return SqliteSaver(connection)


def build_graph(deps: NodeDeps) -> Any:
    budgets = deps.config.budgets

    def _node(func: Any) -> Any:
        def wrapped(state: AgentState) -> dict:
            return func(state, deps)

        return wrapped

    def after_design(state: AgentState) -> Literal["write_capr", "report"]:
        if state.get("not_expressible"):
            return "report"
        return "write_capr"

    def after_write_capr(state: AgentState) -> Literal["generate", "design", "report"]:
        if not state.get("capr_errors"):
            return "generate"
        if deps.budget_stop_reason() or state["iteration"] >= budgets.design_iterations:
            return "report"
        return "design"

    def after_assess(state: AgentState) -> Literal["design", "evaluate", "report"]:
        action = state.get("next_action")
        if action == "done" or deps.budget_stop_reason():
            return "report"

        evaluations_left = deps.tools.budget.evaluate_calls_used < budgets.evaluate_calls
        iterations_exhausted = state["iteration"] >= budgets.design_iterations

        if action == "evaluate" and evaluations_left:
            return "evaluate"
        if iterations_exhausted:
            # The iteration budget forces the transition; spend a remaining evaluation if the
            # cohort is usable, otherwise report what we have.
            if evaluations_left and final_cohort_size(state.get("latest_counts")) > 0:
                return "evaluate"
            return "report"
        return "design"

    def after_evaluate(state: AgentState) -> Literal["diagnose", "report"]:
        if state.get("next_action") == "done" or deps.budget_stop_reason():
            return "report"
        return "diagnose"

    def after_diagnose(state: AgentState) -> Literal["design", "report"]:
        if state["iteration"] >= budgets.design_iterations or deps.budget_stop_reason():
            return "report"
        return "design"

    graph = StateGraph(AgentState)
    graph.add_node("intake", _node(intake.run))
    graph.add_node("survey", _node(survey.run))
    graph.add_node("design", _node(design.run))
    graph.add_node("write_capr", _node(write_capr.run))
    graph.add_node("generate", _node(generate.run))
    graph.add_node("measure", _node(measure.run))
    graph.add_node("assess", _node(assess.run))
    graph.add_node("evaluate", _node(evaluate.run))
    graph.add_node("diagnose", _node(diagnose.run))
    graph.add_node("report", _node(report.run))

    graph.set_entry_point("intake")
    graph.add_edge("intake", "survey")
    graph.add_edge("survey", "design")
    graph.add_conditional_edges("design", after_design)
    graph.add_conditional_edges("write_capr", after_write_capr)
    graph.add_edge("generate", "measure")
    graph.add_edge("measure", "assess")
    graph.add_conditional_edges("assess", after_assess)
    graph.add_conditional_edges("evaluate", after_evaluate)
    graph.add_conditional_edges("diagnose", after_diagnose)
    graph.add_edge("report", END)
    return graph


class AgentRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.tools = ToolFacade(config)
        self.ledger_store = LedgerStore(config.runs_dir)
        self.runtime = LLMRuntime(config, LLMEventLogger(config.runs_dir))
        self.deps = NodeDeps(
            config=config,
            tools=self.tools,
            runtime=self.runtime,
            ledger_store=self.ledger_store,
            budget_guard=BudgetGuard(wall_clock_minutes=config.budgets.wall_clock_minutes),
        )

    def run(self, resume: bool = False) -> AgentState:
        checkpointer = _make_checkpointer(self.config)
        compiled = build_graph(self.deps).compile(checkpointer=checkpointer)
        run_config: dict[str, Any] = {"recursion_limit": RECURSION_LIMIT}
        if checkpointer is not None:
            run_config["configurable"] = {"thread_id": self.config.run_id}
        try:
            entry_state = None if (resume and checkpointer is not None) else initial_state()
            return compiled.invoke(entry_state, config=run_config)
        finally:
            self.tools.close()
            closer = getattr(checkpointer, "conn", None)
            if closer is not None:
                try:
                    closer.close()
                except Exception:
                    pass
