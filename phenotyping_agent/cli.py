from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

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
    reasoning_tier_provider: str | None = typer.Option(
        None,
        help="LLM provider for reasoning tier: 'openai', 'azure_openai', 'anthropic', or 'none' for dry-run."
    ),
    reasoning_tier_model: str | None = typer.Option(
        None,
        help="Model name for reasoning tier (e.g., 'gpt-4o', 'claude-3-5-sonnet-20241022')."
    ),
    fast_tier_provider: str | None = typer.Option(
        None,
        help="LLM provider for fast tier: 'openai', 'azure_openai', 'anthropic', or 'none' for dry-run."
    ),
    fast_tier_model: str | None = typer.Option(
        None,
        help="Model name for fast tier (e.g., 'gpt-4o-mini', 'claude-3-5-haiku-20241022')."
    ),
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=project_root,
        clinical_definition_path=(project_root / clinical_definition),
        phenotype=phenotype,
        dry_run=dry_run,
        max_iterations=max_iterations,
        run_id=run_id,
        reasoning_tier_provider=reasoning_tier_provider,
        reasoning_tier_model=reasoning_tier_model,
        fast_tier_provider=fast_tier_provider,
        fast_tier_model=fast_tier_model,
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
        reasoning_tier_provider=None,
        reasoning_tier_model=None,
        fast_tier_provider=None,
        fast_tier_model=None,
    )
    tools = AgentRunner(config).tools
    for name in sorted(tools.client.list_tools()):
        console.print(name)


if __name__ == "__main__":
    app()

