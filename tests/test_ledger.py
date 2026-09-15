from __future__ import annotations

from pathlib import Path

from phenotyping_agent.context import ledger_block, verdict_tally
from phenotyping_agent.ledger import LedgerStore, render_ledger_markdown
from phenotyping_agent.state import (
    AttritionSummary,
    Design,
    Expectation,
    ExpectationVerdict,
    KeeperMetrics,
    LedgerEntry,
    merge_ledger,
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


def _numbered(iteration: int, **overrides) -> LedgerEntry:
    entry = _entry()
    return entry.model_copy(update={"iteration": iteration, **overrides})


def test_merge_ledger_replaces_an_amended_iteration(tmp_path: Path) -> None:
    """`evaluate` and `diagnose` amend the entry `assess` already wrote."""
    keeper = KeeperMetrics(sensitivity=0.9, specificity=0.9, ppv=0.9, tp=1, fp=1, tn=1, fn=1)
    existing = [_numbered(1), _numbered(2)]

    merged = merge_ledger(existing, [_numbered(2, keeper=keeper)])

    assert [item.iteration for item in merged] == [1, 2]
    assert merged[1].keeper is not None


def test_ledger_store_upserts_by_iteration(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path)
    store.append(_numbered(1))
    store.append(_numbered(1, interpretation="amended"))

    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].interpretation == "amended"


def test_old_unevaluated_entries_are_compacted_in_prompts() -> None:
    keeper = KeeperMetrics(sensitivity=0.9, specificity=0.9, ppv=0.9, tp=1, fp=1, tn=1, fn=1)
    entries = [_numbered(index) for index in range(1, 7)]
    entries[1] = entries[1].model_copy(update={"keeper": keeper})

    rendered = ledger_block(entries, full_detail_last=2)

    assert "Iteration 1 (compacted)" in rendered
    assert "### Iteration 2" in rendered, "evaluated iterations always keep full detail"
    assert "### Iteration 6" in rendered, "recent iterations keep full detail"


def test_verdict_tally_counts_every_verdict() -> None:
    expectation = _entry().expectations[0]
    verdicts = [
        ExpectationVerdict(expectation=expectation, observed="o", verdict=kind, reasoning="r")
        for kind in ("held", "held", "violated", "uninformative")
    ]
    entries = [_numbered(1, verdicts=verdicts)]

    assert verdict_tally(entries) == {"held": 2, "violated": 1, "uninformative": 1}
    assert "| 1 |" in render_ledger_markdown(entries)
