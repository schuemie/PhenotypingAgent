from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from phenotyping_agent.config import build_config
from phenotyping_agent.graph import AgentRunner

app = typer.Typer(help="Autonomous cohort developer agent")
console = Console()


@app.command("run")
def run(
    clinical_definition: str = typer.Option(..., help="Path to clinical definition text file."),
    phenotype: str | None = typer.Option(None, help="Optional phenotype name override."),
    dry_run: bool = typer.Option(True, help="Use fixture-backed fake MCP tools."),
    max_iterations: int | None = typer.Option(None, help="Optional cap on design iterations for this run."),
    run_id: str | None = typer.Option(None, help="Run folder identifier."),
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=project_root,
        clinical_definition_path=(project_root / clinical_definition),
        phenotype=phenotype,
        dry_run=dry_run,
        max_iterations=max_iterations,
        run_id=run_id,
    )
    state = AgentRunner(config).run()
    console.print(f"Run complete. Report: [bold]{config.runs_dir / 'report.md'}[/bold]")
    console.print(f"Final action: {state['next_action']}")


@app.command("list-tools")
def list_tools(
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="List fake tools in dry-run or discover live MCP tools."),
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=project_root,
        clinical_definition_path=project_root / "acute liver failure.txt",
        phenotype="Acute liver failure",
        dry_run=dry_run,
    )
    tools = AgentRunner(config).tools
    for name in sorted(tools.client.list_tools()):
        console.print(name)


if __name__ == "__main__":
    app()

