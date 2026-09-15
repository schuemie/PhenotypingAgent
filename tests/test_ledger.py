from __future__ import annotations

from pathlib import Path

from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.state import (
    AttritionSummary,
    Design,
    Expectation,
    LedgerEntry,
)


def _entry() -> LedgerEntry:
    return LedgerEntry(
        iteration=1,
        hypothesis="Test hypothesis",
        change_from_previous="Initial run",
        design=Design(
            hypothesis="Test hypothesis",
            entry_event="diagnosis",
            concept_sets=["cs_test"],
            inclusion_rules=["Include everyone"],
            exclusion_rules=[],
            temporal_logic="index event only",
        ),
        capr_code="cohort()",
        cohort_id=123,
        expectations=[
            Expectation(
                diagnostic="cohortCount",
                target="overall count",
                claim_kind="direction",
                claim="should be non-zero",
                would_falsify="Count is zero",
                rationale="Sanity check",
                basis="clinical_reasoning",
            )
        ],
        counts=AttritionSummary(),
    )


def test_ledger_store_writes_pretty_printed_json(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path)
    store.append(_entry())

    content = (tmp_path / "ledger.json").read_text(encoding="utf-8")
    assert content.startswith("[\n")
    assert '  {' in content
    assert '    "iteration": 1' in content

    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].cohort_id == 123

