from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class Budgets:
    design_iterations: int = 8
    capr_repair_attempts: int = 4
    evaluate_calls: int = 3
    sample_profiles_per_eval: int = 6
    wall_clock_minutes: int = 120


@dataclass(slots=True)
class ModelTier:
    provider: Literal["azure_openai", "anthropic", "none"] = "none"
    model: str = ""


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    clinical_definition_path: Path
    phenotype: str | None
    dry_run: bool
    run_id: str
    budgets: Budgets
    reasoning_tier: ModelTier
    fast_tier: ModelTier

    @property
    def runs_dir(self) -> Path:
        return self.project_root / "runs" / self.run_id

    @property
    def capr_reference_path(self) -> Path:
        return self.project_root / ".agents" / "skills" / "cohort-developer" / "CAPR_REFERENCE.md"

    @property
    def mcp_config_path(self) -> Path:
        return self.project_root / ".vscode" / "mcp.json"


def build_config(
    project_root: Path,
    clinical_definition_path: Path,
    phenotype: str | None,
    dry_run: bool,
    max_iterations: int | None = None,
    run_id: str | None = None,
) -> AppConfig:
    budgets = Budgets()
    if max_iterations is not None:
        budgets.design_iterations = max_iterations
    return AppConfig(
        project_root=project_root,
        clinical_definition_path=clinical_definition_path,
        phenotype=phenotype,
        dry_run=dry_run,
        run_id=run_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
        budgets=budgets,
        reasoning_tier=ModelTier(provider="none", model="reasoning-dry-run"),
        fast_tier=ModelTier(provider="none", model="fast-dry-run"),
    )

