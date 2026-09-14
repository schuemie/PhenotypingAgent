from __future__ import annotations

from pathlib import Path

from phenotyping_agent.ledger import render_ledger_markdown
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import AgentState


def run(state: AgentState, tools: ToolFacade, run_dir: Path) -> AgentState:
    capr_code = state.get("current_capr") or ""
    capr_json = tools.convert_capr_to_json(capr_code) if capr_code else "{}"

    report_text = "\n".join(
        [
            f"# Phenotyping Report: {state['phenotype']}",
            "",
            "## Final Capr",
            "```r",
            capr_code,
            "```",
            "",
            "## Iteration Ledger",
            render_ledger_markdown(state.get("ledger", [])),
            "",
            "## Notes",
            "- This v1 run uses deterministic design/write nodes for unattended dry-run reliability.",
            "- Convert-to-JSON is written directly without semantic verification by design.",
        ]
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.md").write_text(report_text, encoding="utf-8")
    (run_dir / "final_cohort.json").write_text(capr_json, encoding="utf-8")
    state["final_report"] = report_text
    return state

