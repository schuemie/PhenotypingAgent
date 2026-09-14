from pathlib import Path

from phenotyping_agent.config import build_config
from phenotyping_agent.graph import AgentRunner


def test_dry_run_generates_report() -> None:
    root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=root,
        clinical_definition_path=root / "acute liver failure.txt",
        phenotype="Acute liver failure",
        dry_run=True,
        run_id="test_run",
    )
    state = AgentRunner(config).run()
    assert state["final_report"] is not None
    assert (config.runs_dir / "report.md").exists()


