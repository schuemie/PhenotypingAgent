from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator


class ConceptSetSummary(BaseModel):
    concept_set_name: str
    with_descendants: bool
    person_count: int


class Design(BaseModel):
    hypothesis: str
    entry_event: str
    concept_sets: list[str] = Field(default_factory=list)
    inclusion_rules: list[str] = Field(default_factory=list)
    exclusion_rules: list[str] = Field(default_factory=list)
    temporal_logic: str


class Expectation(BaseModel):
    diagnostic: Literal[
        "cohortCount",
        "incidenceRate",
        "conceptSetOverlap",
        "measurementValues",
        "keeperMetrics",
    ]
    target: str
    claim_kind: Literal["relational", "magnitude_band", "direction"]
    claim: str
    would_falsify: str
    rationale: str
    basis: Literal["clinical_reasoning", "supplied_by_user", "retrieved_from_source"]
    source: str | None = None

    @model_validator(mode="after")
    def validate_expectation(self) -> "Expectation":
        if not self.would_falsify.strip():
            raise ValueError("would_falsify must be a concrete observation")
        has_digit = any(ch.isdigit() for ch in self.claim)
        if self.basis == "clinical_reasoning" and has_digit and self.claim_kind == "direction":
            raise ValueError(
                "Numeric clinically reasoned claims must use claim_kind='magnitude_band'"
            )
        if self.basis == "retrieved_from_source" and not self.source:
            raise ValueError("source is required when basis='retrieved_from_source'")
        return self


class ExpectationVerdict(BaseModel):
    expectation: Expectation
    observed: str
    verdict: Literal["held", "violated", "uninformative"]
    reasoning: str


class AttritionRow(BaseModel):
    rule_sequence: int
    name: str
    incremental_persons: int | None = None
    marginal_person: int | None = None
    gain_count: int | None = None


class AttritionSummary(BaseModel):
    rows: list[AttritionRow] = Field(default_factory=list)


class IncidenceRow(BaseModel):
    stratum: str
    stratum_name: str
    persons: float
    events: float
    person_years: float
    incidence_rate_per_1000_person_years: float | None = None


class IncidenceSummary(BaseModel):
    rows: list[IncidenceRow] = Field(default_factory=list)
    note: str | None = Field(
        default=None,
        description="Message returned instead of rows, e.g. 'No observation time found'.",
    )


class KeeperMetrics(BaseModel):
    sensitivity: float
    specificity: float
    ppv: float
    tp: int
    fp: int
    tn: int
    fn: int


class FailureMode(BaseModel):
    """A hypothesised reason the cohort mis-classifies people."""

    pattern: str
    evidence_person_count: int = 0
    mechanism: str = Field(
        description="Clinical or data-capture mechanism. Person-level anecdotes are not a mechanism."
    )
    proposed_design_change: str
    expected_metric_effect: str


class LedgerEntry(BaseModel):
    iteration: int
    hypothesis: str
    change_from_previous: str
    design: Design
    capr_code: str
    cohort_id: int | None
    expectations: list[Expectation] = Field(default_factory=list)
    verdicts: list[ExpectationVerdict] = Field(default_factory=list)
    counts: AttritionSummary = Field(default_factory=AttritionSummary)
    incidence_rates: IncidenceSummary = Field(default_factory=IncidenceSummary)
    keeper: KeeperMetrics | None = None
    interpretation: str = ""
    next_action: Literal["iterate", "evaluate", "done"] = "iterate"
    attrition_mechanisms: list[str] = Field(default_factory=list)
    readiness_rationale: str = ""
    failure_modes: list[FailureMode] = Field(default_factory=list)
    gate_blockers: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Structured LLM output schemas
# --------------------------------------------------------------------------------------


class DesignOutput(BaseModel):
    """Structured result of the `design` node."""

    design: Design
    change_from_previous: str = Field(
        description="What changed relative to the previous iteration, or 'Initial draft'."
    )
    expectations: list[Expectation] = Field(
        default_factory=list,
        description=(
            "Expectations to pre-register for the diagnostics that will run after cohort "
            "generation. Must include cohortCount/overall and incidenceRate/overall."
        ),
    )
    not_expressible: bool = False
    not_expressible_reason: str | None = None


class RawVerdict(BaseModel):
    """A verdict referring to a pre-registered expectation by position."""

    expectation_index: int
    observed: str
    verdict: Literal["held", "violated", "uninformative"]
    reasoning: str


class AssessOutput(BaseModel):
    """Structured result of the `assess` node."""

    verdicts: list[RawVerdict] = Field(default_factory=list)
    interpretation: str = ""
    attrition_mechanisms: list[str] = Field(default_factory=list)
    readiness_rationale: str = ""
    next_action: Literal["iterate", "evaluate", "done"] = "iterate"


class DiagnoseOutput(BaseModel):
    """Structured result of the `diagnose` node."""

    summary: str = ""
    failure_modes: list[FailureMode] = Field(default_factory=list)


def merge_ledger(existing: list[LedgerEntry], incoming: list[LedgerEntry]) -> list[LedgerEntry]:
    """Reducer for `AgentState.ledger`.

    Appends new iterations, but *replaces* an entry with the same iteration number. `evaluate`
    and `diagnose` run after `assess` has already written the entry, so they need to amend it
    rather than duplicate it.
    """
    merged: dict[int, LedgerEntry] = {entry.iteration: entry for entry in existing}
    for entry in incoming:
        merged[entry.iteration] = entry
    return [merged[key] for key in sorted(merged)]


class AgentState(TypedDict):
    phenotype: str
    clinical_definition: str
    database_description: str
    available_concept_sets: list[ConceptSetSummary]
    concept_set_registry: dict[str, str]
    current_design: Design | None
    current_capr: str | None
    current_cohort_id: int | None
    pending_expectations: list[Expectation]
    used_expectations: list[Expectation]
    ledger: Annotated[list[LedgerEntry], merge_ledger]
    next_action: Literal["iterate", "evaluate", "done"]
    final_report: str | None
    iteration: int
    evaluate_calls: int
    # Diagnostics captured by `measure` / `evaluate`, typed instead of smuggled.
    latest_counts: AttritionSummary | None
    latest_incidence: IncidenceSummary | None
    latest_overlap: list[dict]
    latest_measurements: list[dict]
    latest_keeper: KeeperMetrics | None
    latest_profiles: list[dict]
    # Control / bookkeeping
    change_from_previous: str
    capr_errors: list[str]
    failure_modes: list[FailureMode]
    concept_set_gaps: list[str]
    not_expressible: bool
    not_expressible_reason: str | None
    stop_reason: str | None
    gate_blockers: list[str]


