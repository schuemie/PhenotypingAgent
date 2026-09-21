from __future__ import annotations

import csv
import re
from importlib import util
from pathlib import Path

import typer
from rich.console import Console

# Load environment variables from .env file if it exists
if util.find_spec("dotenv") is not None:
    from dotenv import load_dotenv
    load_dotenv()


from phenotyping_agent.config import build_config
from phenotyping_agent.graph import AgentRunner
from phenotyping_agent.state import AgentState

app = typer.Typer(help="Autonomous cohort developer agent")
console = Console()


def _sanitize_run_id(phenotype: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z]+", "_", phenotype).strip("_")
    if not sanitized:
        raise typer.BadParameter("Phenotype names must contain at least one alphanumeric character.")
    return f"langgraph__{sanitized}"


def _unique_run_id(project_root: Path, base_run_id: str) -> str:
    runs_dir = project_root / "runs"
    candidate = base_run_id
    suffix = 2
    while (runs_dir / candidate).exists():
        candidate = f"{base_run_id}_{suffix}"
        suffix += 1
    return candidate


def _write_definition_file(project_root: Path, run_id: str, definition: str) -> Path:
    run_dir = project_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    definition_path = run_dir / "clinical_definition.txt"
    definition_path.write_text(definition.strip() + "\n", encoding="utf-8")
    return definition_path


def _load_phenotypes_csv(csv_path: Path) -> list[tuple[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise typer.BadParameter(f"{csv_path} is empty or missing a header row.")

        header_map = {name.strip(): name for name in reader.fieldnames if name}
        missing = {"phenotype", "definition"} - set(header_map)
        if missing:
            required = ", ".join(sorted({"phenotype", "definition"}))
            raise typer.BadParameter(f"{csv_path} must contain columns named: {required}.")

        rows: list[tuple[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            phenotype = (row.get(header_map["phenotype"]) or "").strip()
            definition = (row.get(header_map["definition"]) or "").strip()
            if not phenotype or not definition:
                raise typer.BadParameter(
                    f"Row {line_number} in {csv_path} must include non-empty phenotype and definition values."
                )
            rows.append((phenotype, definition))

    if not rows:
        raise typer.BadParameter(f"{csv_path} does not contain any phenotype rows.")
    return rows


def _execute_run(
    *,
    project_root: Path,
    clinical_definition_path: Path,
    phenotype: str | None,
    dry_run: bool,
    max_iterations: int | None,
    run_id: str | None,
    reasoning_tier_provider: str | None,
    reasoning_tier_model: str | None,
    fast_tier_provider: str | None,
    fast_tier_model: str | None,
    resume: bool,
) -> tuple[Path, AgentState]:
    config = build_config(
        project_root=project_root,
        clinical_definition_path=clinical_definition_path,
        phenotype=phenotype,
        dry_run=dry_run,
        max_iterations=max_iterations,
        run_id=run_id,
        reasoning_tier_provider=reasoning_tier_provider,
        reasoning_tier_model=reasoning_tier_model,
        fast_tier_provider=fast_tier_provider,
        fast_tier_model=fast_tier_model,
    )
    state = AgentRunner(config).run(resume=resume)
    return config.runs_dir, state


@app.command("run")
def run(
    clinical_definition: Path | None = typer.Option(None, help="Path to clinical definition text file."),
    phenotypes_csv: Path | None = typer.Option(
        None,
        "--phenotypes-csv",
        help="CSV file with `phenotype` and `definition` columns; runs each row sequentially.",
    ),
    phenotype: str | None = typer.Option(None, help="Optional phenotype name override."),
    dry_run: bool = typer.Option(False, help="Use fixture-backed fake MCP tools (special case)."),
    max_iterations: int | None = typer.Option(None, help="Optional cap on design iterations for this run."),
    run_id: str | None = typer.Option(None, help="Run folder identifier."),
    reasoning_tier_provider: str | None = typer.Option(
        None,
        help="LLM provider for reasoning tier: 'openai', 'azure_openai', 'anthropic', 'bedrock', or 'none' for dry-run."
    ),
    reasoning_tier_model: str | None = typer.Option(
        None,
        help="Model name for reasoning tier (e.g., 'gpt-4o', 'claude-3-5-sonnet-20241022', 'anthropic.claude-3-opus-20240229-v1:0')."
    ),
    fast_tier_provider: str | None = typer.Option(
        None,
        help="LLM provider for fast tier: 'openai', 'azure_openai', 'anthropic', 'bedrock', or 'none' for dry-run."
    ),
    fast_tier_model: str | None = typer.Option(
        None,
        help="Model name for fast tier (e.g., 'gpt-4o-mini', 'claude-3-5-haiku-20241022', 'anthropic.claude-3-haiku-20240307-v1:0')."
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume an interrupted run from its checkpoint. Requires --run-id and the "
             "langgraph-checkpoint-sqlite package.",
    ),
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    if phenotypes_csv is not None:
        if clinical_definition is not None or phenotype is not None or run_id is not None or resume:
            raise typer.BadParameter(
                "--phenotypes-csv cannot be combined with --clinical-definition, --phenotype, --run-id, or --resume."
            )
        for phenotype_name, definition in _load_phenotypes_csv(project_root / phenotypes_csv):
            base_run_id = _sanitize_run_id(phenotype_name)
            batch_run_id = _unique_run_id(project_root, base_run_id)
            definition_path = _write_definition_file(project_root, batch_run_id, definition)
            runs_dir, state = _execute_run(
                project_root=project_root,
                clinical_definition_path=definition_path,
                phenotype=phenotype_name,
                dry_run=dry_run,
                max_iterations=max_iterations,
                run_id=batch_run_id,
                reasoning_tier_provider=reasoning_tier_provider,
                reasoning_tier_model=reasoning_tier_model,
                fast_tier_provider=fast_tier_provider,
                fast_tier_model=fast_tier_model,
                resume=False,
            )
            console.print(f"Run complete for [bold]{phenotype_name}[/bold]. Report: [bold]{runs_dir / 'report.md'}[/bold]")
            console.print(f"Final action: {state['next_action']}")
            if state.get("stop_reason"):
                console.print(f"Stop reason: {state['stop_reason']}")
        return

    if clinical_definition is None:
        raise typer.BadParameter("Either --clinical-definition or --phenotypes-csv is required.")
    if resume and not run_id:
        raise typer.BadParameter("--resume requires --run-id of the interrupted run.")
    runs_dir, state = _execute_run(
        project_root=project_root,
        clinical_definition_path=project_root / clinical_definition,
        phenotype=phenotype,
        dry_run=dry_run,
        max_iterations=max_iterations,
        run_id=run_id,
        reasoning_tier_provider=reasoning_tier_provider,
        reasoning_tier_model=reasoning_tier_model,
        fast_tier_provider=fast_tier_provider,
        fast_tier_model=fast_tier_model,
        resume=resume,
    )
    console.print(f"Run complete. Report: [bold]{runs_dir / 'report.md'}[/bold]")
    console.print(f"Final action: {state['next_action']}")
    if state.get("stop_reason"):
        console.print(f"Stop reason: {state['stop_reason']}")


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

