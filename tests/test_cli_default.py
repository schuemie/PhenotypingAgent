from pathlib import Path

from typer.testing import CliRunner

import phenotyping_agent.cli as cli


class _FakeRunner:
    def __init__(self, config) -> None:
        self.config = config

    def run(self):
        return {"next_action": "done", "final_report": "ok"}


runner = CliRunner()


def test_run_defaults_to_live_mode(monkeypatch) -> None:
    captured = {}

    def factory(config):
        captured["config"] = config
        return _FakeRunner(config)

    monkeypatch.setattr(cli, "AgentRunner", factory)

    result = runner.invoke(
        cli.app,
        ["run", "--clinical-definition", "acute liver failure.txt", "--run-id", "cli_default_test"],
    )

    assert result.exit_code == 0, result.output
    assert captured["config"].dry_run is False
    assert captured["config"].clinical_definition_path == Path(__file__).resolve().parents[1] / "acute liver failure.txt"

