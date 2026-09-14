import pytest
from pathlib import Path

from phenotyping_agent.config import build_config
from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.state import Expectation


def test_expectation_required_for_diagnostics() -> None:
    root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=root,
        clinical_definition_path=root / "acute liver failure.txt",
        phenotype="Acute liver failure",
        dry_run=True,
        run_id="test_gating",
    )
    tools = ToolFacade(config)
    with pytest.raises(RuntimeError):
        tools.get_cohort_count(101)


def test_expectation_allows_call() -> None:
    root = Path(__file__).resolve().parents[1]
    config = build_config(
        project_root=root,
        clinical_definition_path=root / "acute liver failure.txt",
        phenotype="Acute liver failure",
        dry_run=True,
        run_id="test_gating_ok",
    )
    tools = ToolFacade(config)
    tools.record_expectation(
        Expectation(
            diagnostic="cohortCount",
            target="overall",
            claim_kind="direction",
            claim="Non-zero",
            would_falsify="Count is zero",
            rationale="Rare disease should still occur",
            basis="clinical_reasoning",
        )
    )
    out = tools.get_cohort_count(101)
    assert out


