from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator


class ConceptSetSummary(BaseModel):
    concept_set_name: str
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


class KeeperMetrics(BaseModel):
    sensitivity: float
    specificity: float
    ppv: float
    tp: int
    fp: int
    tn: int
    fn: int


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
    ledger: Annotated[list[LedgerEntry], operator.add]
    next_action: Literal["iterate", "evaluate", "done"]
    final_report: str | None
    iteration: int
    evaluate_calls: int


