from __future__ import annotations

import os
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
    provider: Literal["openai", "azure_openai", "anthropic", "none"] = "none"
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


def _get_model_tier_from_env(env_prefix: str) -> ModelTier:
    """Load model tier configuration from environment variables.

    Args:
        env_prefix: Prefix for environment variables (e.g., "REASONING", "FAST")

    Returns:
        ModelTier with provider and model from environment, or dry-run defaults if not set
    """
    provider_var = f"{env_prefix}_TIER_PROVIDER"
    model_var = f"{env_prefix}_TIER_MODEL"

    provider = os.getenv(provider_var, "none")
    model = os.getenv(model_var, "")

    return ModelTier(provider=provider, model=model)


def build_config(
    project_root: Path,
    clinical_definition_path: Path,
    phenotype: str | None,
    dry_run: bool,
    max_iterations: int | None = None,
    run_id: str | None = None,
    reasoning_tier_provider: str | None = None,
    reasoning_tier_model: str | None = None,
    fast_tier_provider: str | None = None,
    fast_tier_model: str | None = None,
) -> AppConfig:
    """Build application configuration.

    Args:
        project_root: Root directory of the project
        clinical_definition_path: Path to clinical definition file
        phenotype: Optional phenotype name override
        dry_run: Whether to use fixture-backed fake MCP tools
        max_iterations: Optional cap on design iterations
        run_id: Optional run identifier
        reasoning_tier_provider: LLM provider for reasoning tier (openai, azure_openai, anthropic)
        reasoning_tier_model: Model name for reasoning tier
        fast_tier_provider: LLM provider for fast tier
        fast_tier_model: Model name for fast tier

    Returns:
        AppConfig instance
    """
    budgets = Budgets()
    if max_iterations is not None:
        budgets.design_iterations = max_iterations

    # Load from CLI args or environment variables
    reasoning_provider = reasoning_tier_provider or os.getenv("REASONING_TIER_PROVIDER", "none")
    reasoning_model = reasoning_tier_model or os.getenv("REASONING_TIER_MODEL", "reasoning-dry-run")

    fast_provider = fast_tier_provider or os.getenv("FAST_TIER_PROVIDER", "none")
    fast_model = fast_tier_model or os.getenv("FAST_TIER_MODEL", "fast-dry-run")

    return AppConfig(
        project_root=project_root,
        clinical_definition_path=clinical_definition_path,
        phenotype=phenotype,
        dry_run=dry_run,
        run_id=run_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
        budgets=budgets,
        reasoning_tier=ModelTier(provider=reasoning_provider, model=reasoning_model),
        fast_tier=ModelTier(provider=fast_provider, model=fast_model),
    )

