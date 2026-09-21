from pathlib import Path

from typer.testing import CliRunner

import phenotyping_agent.cli as cli


class _FakeRunner:
    def __init__(self, config, seen) -> None:
        self.config = config
        self.seen = seen

    def run(self, resume: bool = False):
        self.seen.append((self.config.run_id, self.config.phenotype, self.config.clinical_definition_path, resume))
        return {"next_action": "done", "final_report": "ok", "stop_reason": None}


runner = CliRunner()


def test_run_can_process_phenotypes_csv_sequentially(monkeypatch, tmp_path) -> None:
    seen: list[tuple[str, str | None, Path, bool]] = []
    captured_configs = []

    def factory(config):
        captured_configs.append(config)
        return _FakeRunner(config, seen)

    project_root = tmp_path / "project"
    monkeypatch.setattr(cli, "__file__", str(project_root / "phenotyping_agent" / "cli.py"))
    monkeypatch.setattr(cli, "AgentRunner", factory)

    csv_path = tmp_path / "phenotypes.csv"
    csv_path.write_text(
        "phenotype,definition\n"
        "Crohn's disease,Crohn definition text\n"
        "Major Depressive Disorder,MDD definition text\n",
        encoding="utf-8",
    )

    result = runner.invoke(cli.app, ["run", "--phenotypes-csv", str(csv_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert [config.run_id for config in captured_configs] == [
        "langgraph__Crohn_s_disease",
        "langgraph__Major_Depressive_Disorder",
    ]
    assert [config.phenotype for config in captured_configs] == [
        "Crohn's disease",
        "Major Depressive Disorder",
    ]
    assert seen == [
        (
            "langgraph__Crohn_s_disease",
            "Crohn's disease",
            project_root / "runs" / "langgraph__Crohn_s_disease" / "clinical_definition.txt",
            False,
        ),
        (
            "langgraph__Major_Depressive_Disorder",
            "Major Depressive Disorder",
            project_root / "runs" / "langgraph__Major_Depressive_Disorder" / "clinical_definition.txt",
            False,
        ),
    ]
    assert (project_root / "runs" / "langgraph__Crohn_s_disease" / "clinical_definition.txt").read_text(encoding="utf-8") == "Crohn definition text\n"
    assert (project_root / "runs" / "langgraph__Major_Depressive_Disorder" / "clinical_definition.txt").read_text(encoding="utf-8") == "MDD definition text\n"

