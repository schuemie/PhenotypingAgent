"""Prompt context rendering.

Everything an LLM node needs to know about the run is assembled here so that all prompts
share one consistent, compacted view of the state.
"""

from __future__ import annotations

from typing import Any, Iterable

from phenotyping_agent.state import (
    AgentState,
    AttritionSummary,
    ConceptSetSummary,
    Design,
    Expectation,
    FailureMode,
    IncidenceSummary,
    KeeperMetrics,
    LedgerEntry,
)

# Repeated verbatim in every prompt that can register expectations. Mirrors the validator in
# `state.Expectation` so the model is told the rules rather than discovering them via errors.
EXPECTATION_RULES = """\
Rules for registering expectations (enforced in code - violations are rejected):
- `would_falsify` must name a concrete observation, never a sentiment such as
  "implausible for a rare disease".
- A numeric claim derived from clinical reasoning must use `claim_kind="magnitude_band"` and
  span at least an order of magnitude. Point estimates are rejected. Precise figures require
  `basis="supplied_by_user"` or `basis="retrieved_from_source"` with a populated `source`.
- Prefer at least one `relational` claim per diagnostic (age gradient, sex ratio, "smaller than
  iteration 3", "this exclusion removes under 20%"). Relational claims need no external
  benchmark and are usually more diagnostic than absolute rates: incidence in a commercially
  insured, under-65-skewed database is not population incidence.
- Register the expectation BEFORE the diagnostic runs. The point is the ordering, not the
  accuracy: fixing the claim before the result arrives is what prevents a plausible story being
  constructed for any number."""


def concept_set_table(summaries: Iterable[ConceptSetSummary]) -> str:
    rows = list(summaries)
    if not rows:
        return "No pre-computed concept sets are available."
    lines = ["| Concept set name | With descendants | Person count |", "|---|---|---:|"]
    for row in rows:
        lines.append(
            f"| {row.concept_set_name} | {'Y' if row.with_descendants else 'N'} | {row.person_count} |"
        )
    return "\n".join(lines)


def design_block(design: Design | None) -> str:
    if design is None:
        return "No design yet."
    inclusion = [f"  - {rule}" for rule in design.inclusion_rules] or ["  - none"]
    exclusion = [f"  - {rule}" for rule in design.exclusion_rules] or ["  - none"]
    parts = [
        f"Hypothesis: {design.hypothesis}",
        f"Entry event: {design.entry_event}",
        f"Concept sets: {', '.join(design.concept_sets) or 'none'}",
        "Inclusion rules:",
        *inclusion,
        "Exclusion rules:",
        *exclusion,
        f"Temporal logic: {design.temporal_logic}",
    ]
    return "\n".join(parts)


def expectations_block(expectations: Iterable[Expectation]) -> str:
    rows = list(expectations)
    if not rows:
        return "No expectations were registered."
    lines = []
    for index, item in enumerate(rows):
        lines.append(
            f"[{index}] diagnostic={item.diagnostic} target={item.target} "
            f"kind={item.claim_kind} basis={item.basis}\n"
            f"     claim: {item.claim}\n"
            f"     would_falsify: {item.would_falsify}\n"
            f"     rationale: {item.rationale}"
        )
    return "\n".join(lines)


def counts_block(summary: AttritionSummary | None) -> str:
    if summary is None or not summary.rows:
        return "No cohort counts available."
    lines = ["| # | Rule | Incremental persons | Marginal persons | Gain |", "|---:|---|---:|---:|---:|"]
    for row in summary.rows:
        lines.append(
            f"| {row.rule_sequence} | {row.name} | {row.incremental_persons if row.incremental_persons is not None else ''} "
            f"| {row.marginal_person if row.marginal_person is not None else ''} "
            f"| {row.gain_count if row.gain_count is not None else ''} |"
        )
    return "\n".join(lines)


def incidence_block(summary: IncidenceSummary | None) -> str:
    if summary is None:
        return "No incidence rates available."
    if not summary.rows:
        return summary.note or "No incidence rates available."
    lines = ["| Stratum | Persons | Events | Person-years | Rate /1000 PY |", "|---|---:|---:|---:|---:|"]
    for row in summary.rows:
        rate = (
            f"{row.incidence_rate_per_1000_person_years:.4g}"
            if row.incidence_rate_per_1000_person_years is not None
            else ""
        )
        lines.append(
            f"| {row.stratum_name} | {row.persons:.0f} | {row.events:.0f} | {row.person_years:.0f} | {rate} |"
        )
    return "\n".join(lines)


def keeper_block(metrics: KeeperMetrics | None) -> str:
    if metrics is None:
        return "No KEEPER evaluation has been run."
    return (
        f"sensitivity={metrics.sensitivity:.3f} specificity={metrics.specificity:.3f} "
        f"ppv={metrics.ppv:.3f} tp={metrics.tp} fp={metrics.fp} tn={metrics.tn} fn={metrics.fn}"
    )


def failure_modes_block(modes: Iterable[FailureMode]) -> str:
    rows = list(modes)
    if not rows:
        return "No failure modes diagnosed yet."
    return "\n".join(
        f"- {m.pattern} (n~{m.evidence_person_count})\n"
        f"  mechanism: {m.mechanism}\n"
        f"  proposed change: {m.proposed_design_change}\n"
        f"  expected effect: {m.expected_metric_effect}"
        for m in rows
    )


def profiles_block(profiles: Iterable[Any], limit: int = 6) -> str:
    rows = list(profiles)[:limit]
    if not rows:
        return "No patient profiles were sampled."
    chunks = []
    for profile in rows:
        if isinstance(profile, dict):
            ptype = profile.get("type", "?")
            body = profile.get("patientProfile", "")
            rationale = profile.get("rationale", "")
            chunks.append(f"### {ptype}\n{body}\n\nAdjudication rationale: {rationale}")
        else:
            chunks.append(str(profile))
    return "\n\n".join(chunks)


def ledger_block(entries: list[LedgerEntry], full_detail_last: int = 3) -> str:
    """Render the ledger for a prompt.

    Recent entries and every evaluated iteration keep full detail; older non-evaluated
    entries compact to a single line (plan section 3).
    """
    if not entries:
        return "No iterations recorded yet. This is the first design."

    keep_full: set[int] = {entry.iteration for entry in entries[-full_detail_last:]}
    keep_full |= {entry.iteration for entry in entries if entry.keeper is not None}

    chunks: list[str] = []
    for entry in entries:
        if entry.iteration not in keep_full:
            held = sum(1 for v in entry.verdicts if v.verdict == "held")
            violated = sum(1 for v in entry.verdicts if v.verdict == "violated")
            final = entry.counts.rows[-1].incremental_persons if entry.counts.rows else None
            chunks.append(
                f"- Iteration {entry.iteration} (compacted): {entry.change_from_previous} | "
                f"final count={final} | verdicts held={held} violated={violated} | "
                f"next={entry.next_action}"
            )
            continue

        verdicts = "\n".join(
            f"  - [{v.verdict}] {v.expectation.diagnostic}/{v.expectation.target}: "
            f"claimed '{v.expectation.claim}'; observed '{v.observed}'. {v.reasoning}"
            for v in entry.verdicts
        ) or "  - none"
        chunks.append(
            "\n".join(
                [
                    f"### Iteration {entry.iteration}",
                    f"Change from previous: {entry.change_from_previous}",
                    f"Hypothesis: {entry.hypothesis}",
                    design_block(entry.design),
                    "Capr:",
                    "```r",
                    entry.capr_code,
                    "```",
                    "Counts:",
                    counts_block(entry.counts),
                    "Incidence:",
                    incidence_block(entry.incidence_rates),
                    f"KEEPER: {keeper_block(entry.keeper)}",
                    "Expectation verdicts:",
                    verdicts,
                    f"Interpretation: {entry.interpretation}",
                    f"Next action: {entry.next_action}",
                ]
            )
        )
    return "\n\n".join(chunks)


def base_context(state: AgentState) -> str:
    """The shared header block rendered into every LLM prompt."""
    return "\n".join(
        [
            f"# Phenotype\n{state['phenotype']}",
            "",
            "# Clinical definition (authoritative - do not invent criteria beyond it)",
            state["clinical_definition"],
            "",
            "# Database description",
            state["database_description"] or "Not available.",
            "",
            "# Pre-computed concept sets available",
            concept_set_table(state["available_concept_sets"]),
            "",
            "# Iteration ledger",
            ledger_block(state.get("ledger", [])),
        ]
    )


def verdict_tally(entries: Iterable[LedgerEntry]) -> dict[str, int]:
    tally = {"held": 0, "violated": 0, "uninformative": 0}
    for entry in entries:
        for verdict in entry.verdicts:
            tally[verdict.verdict] = tally.get(verdict.verdict, 0) + 1
    return tally



