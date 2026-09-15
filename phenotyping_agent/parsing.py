"""Tolerant parsing of MCP tool payloads into the typed state models."""

from __future__ import annotations

from typing import Any

from phenotyping_agent.state import (
    AttritionRow,
    AttritionSummary,
    IncidenceRow,
    IncidenceSummary,
    KeeperMetrics,
)


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_attrition(payload: Any) -> AttritionSummary:
    """Parse `getCohortCount` output.

    The R tool returns two different shapes. When the cohort has inclusion rules it returns one
    row per rule (`ruleSequence`/`name`/`incrementalPersons`/...). When it has none - which is the
    common case for a first-iteration entry-event-only design - it instead returns a single row of
    `personCount`/`entryCount`. Treating the second shape as the first yields a cohort size of 0,
    which would make the Phase 3 gate reject a perfectly good cohort forever.
    """
    rows = _rows(payload)
    if len(rows) == 1 and "ruleSequence" not in rows[0] and "personCount" in rows[0]:
        return AttritionSummary(
            rows=[
                AttritionRow(
                    rule_sequence=0,
                    name="Initial event (no inclusion rules)",
                    incremental_persons=_int_or_none(rows[0].get("personCount")),
                )
            ]
        )

    parsed = [
        AttritionRow(
            rule_sequence=_int_or_none(row.get("ruleSequence")) or index,
            name=str(row.get("name", f"Rule {index}")),
            incremental_persons=_int_or_none(row.get("incrementalPersons")),
            marginal_person=_int_or_none(row.get("marginalPerson")),
            gain_count=_int_or_none(row.get("gainCount")),
        )
        for index, row in enumerate(rows)
    ]
    return AttritionSummary(rows=parsed)


def parse_incidence(payload: Any) -> IncidenceSummary:
    # The tool returns a bare string when the cohort has no observation time. Keep the message:
    # `assess` needs to see it, otherwise the diagnostic silently looks like "no data".
    if isinstance(payload, str):
        return IncidenceSummary(note=payload)
    rows = [
        IncidenceRow(
            stratum=str(row.get("stratum", "Overall")),
            stratum_name=str(row.get("stratumName", row.get("stratum", "Overall"))),
            persons=_float(row.get("persons")),
            events=_float(row.get("events")),
            person_years=_float(row.get("personYears")),
            incidence_rate_per_1000_person_years=(
                _float(row.get("incidenceRatePer1000PersonYears"))
                if row.get("incidenceRatePer1000PersonYears") is not None
                else None
            ),
        )
        for row in _rows(payload)
    ]
    return IncidenceSummary(rows=rows)


def parse_keeper(payload: Any) -> KeeperMetrics | None:
    rows = _rows(payload)
    if not rows:
        return None
    row = rows[0]
    try:
        return KeeperMetrics(
            sensitivity=_float(row.get("sensitivity")),
            specificity=_float(row.get("specificity")),
            ppv=_float(row.get("ppv")),
            tp=_int_or_none(row.get("tp")) or 0,
            fp=_int_or_none(row.get("fp")) or 0,
            tn=_int_or_none(row.get("tn")) or 0,
            fn=_int_or_none(row.get("fn")) or 0,
        )
    except Exception:  # noqa: BLE001 - malformed payloads must not kill the run
        return None


def final_cohort_size(summary: AttritionSummary | None) -> int:
    if summary is None or not summary.rows:
        return 0
    for row in reversed(summary.rows):
        if row.incremental_persons is not None:
            return int(row.incremental_persons)
    return 0


def strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown code fence from an LLM code response."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    lines = lines[1:]
    while lines and lines[-1].strip() != "```":
        lines.pop()
    if lines and lines[-1].strip() == "```":
        lines.pop()
    return "\n".join(lines).strip()




