from __future__ import annotations

from phenotyping_agent.state import (
    AgentState,
    AttritionRow,
    AttritionSummary,
    ExpectationVerdict,
    IncidenceRow,
    IncidenceSummary,
    LedgerEntry,
)


def run(state: AgentState) -> AgentState:
    raw_counts = state.get("_counts", [])  # type: ignore[assignment]
    raw_incidence = state.get("_incidence", [])  # type: ignore[assignment]

    count_rows = [
        AttritionRow(
            rule_sequence=int(r.get("ruleSequence", idx)),
            name=str(r.get("name", f"Rule {idx}")),
            incremental_persons=int(r.get("incrementalPersons", 0)),
            marginal_person=int(r.get("marginalPerson", 0)) if r.get("marginalPerson") is not None else None,
            gain_count=int(r.get("gainCount", 0)) if r.get("gainCount") is not None else None,
        )
        for idx, r in enumerate(raw_counts)
        if isinstance(r, dict)
    ]
    incidence_rows = [
        IncidenceRow(
            stratum=str(r.get("stratum", "Overall")),
            stratum_name=str(r.get("stratumName", "Overall")),
            persons=float(r.get("persons", 0)),
            events=float(r.get("events", 0)),
            person_years=float(r.get("personYears", 0)),
            incidence_rate_per_1000_person_years=float(r.get("incidenceRatePer1000PersonYears", 0))
            if r.get("incidenceRatePer1000PersonYears") is not None
            else None,
        )
        for r in raw_incidence
        if isinstance(r, dict)
    ]

    final_count = count_rows[-1].incremental_persons if count_rows else 0
    next_action = "evaluate" if final_count and final_count > 0 else "iterate"

    expectation_list = state.get("_used_expectations", [])
    verdicts = [
        ExpectationVerdict(
            expectation=e,
            observed="diagnostic captured",
            verdict="uninformative",
            reasoning="Deterministic assessor records the observation; human/LLM interpretation can refine later.",
        )
        for e in expectation_list
    ]

    entry = LedgerEntry(
        iteration=state["iteration"],
        hypothesis=state["current_design"].hypothesis if state["current_design"] else "",
        change_from_previous="Initial executable draft" if state["iteration"] == 1 else "Iterated design",
        design=state["current_design"],
        capr_code=state["current_capr"] or "",
        cohort_id=state["current_cohort_id"],
        expectations=expectation_list,
        verdicts=verdicts,
        counts=AttritionSummary(rows=count_rows),
        incidence_rates=IncidenceSummary(rows=incidence_rows),
        interpretation="Counts and rates captured for gate decision.",
        next_action=next_action,
    )
    state["ledger"] = state.get("ledger", []) + [entry]
    state["next_action"] = next_action
    return state


