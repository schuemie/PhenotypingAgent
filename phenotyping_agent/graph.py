from __future__ import annotations

from phenotyping_agent.config import AppConfig
from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.nodes import assess, design, evaluate, generate, intake, measure, report, survey, write_capr
from phenotyping_agent.state import AgentState


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
        "ledger": [],
        "next_action": "iterate",
        "final_report": None,
        "iteration": 1,
        "evaluate_calls": 0,
    }


class AgentRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.tools = ToolFacade(config)
        self.ledger_store = LedgerStore(config.runs_dir)

    def run(self) -> AgentState:
        try:
            state = initial_state()
            state = intake.run(state, self.config)
            state = survey.run(state, self.tools)

            while state["iteration"] <= self.config.budgets.design_iterations:
                state = design.run(state, self.tools)
                state = write_capr.run(state, self.tools, self.config)
                state = generate.run(state, self.tools)
                state = measure.run(state, self.tools)
                state = assess.run(state)
                self.ledger_store.append(state["ledger"][-1])

                if state["next_action"] == "evaluate":
                    state = evaluate.run(state, self.tools)
                    keeper = state.get("_keeper", [])
                    if keeper and isinstance(keeper, list):
                        metrics = keeper[0]
                        ppv = float(metrics.get("ppv", 0))
                        sensitivity = float(metrics.get("sensitivity", 0))
                        if ppv >= 0.8 and sensitivity >= 0.8:
                            state["next_action"] = "done"
                        elif state["evaluate_calls"] >= self.config.budgets.evaluate_calls:
                            state["next_action"] = "done"
                        else:
                            state["next_action"] = "iterate"

                if state["next_action"] == "done":
                    break
                state["iteration"] += 1

            state = report.run(state, self.tools, self.config.runs_dir)
            return state
        finally:
            self.tools.close()

