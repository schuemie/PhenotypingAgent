"""Parsing of the payload shapes `tools/server.R` actually returns.

These pin behaviour that the fixture-backed dry run cannot exercise, because the fake client
returns only one of each tool's possible shapes.
"""

from __future__ import annotations

from phenotyping_agent.mcp_tools import ToolFacade
from phenotyping_agent.parsing import final_cohort_size, parse_attrition, parse_incidence
from helpers import make_config


def test_cohort_count_without_inclusion_rules_is_not_read_as_an_empty_cohort() -> None:
    """A design with no inclusion rules returns personCount/entryCount, not rule rows."""
    payload = [{"personCount": 1234, "entryCount": 1500, "database": "db"}]

    summary = parse_attrition(payload)

    assert final_cohort_size(summary) == 1234, (
        "misreading this shape would make the Phase 3 gate reject a valid cohort forever"
    )
    assert summary.rows[0].name.startswith("Initial event")


def test_cohort_count_with_inclusion_rules_keeps_the_attrition_table() -> None:
    payload = [
        {"ruleSequence": 0, "name": "Initial event", "incrementalPersons": 500},
        {"ruleSequence": 1, "name": "Adult", "incrementalPersons": 300, "marginalPerson": 310,
         "gainCount": 10},
    ]

    summary = parse_attrition(payload)

    assert len(summary.rows) == 2
    assert final_cohort_size(summary) == 300
    assert summary.rows[1].gain_count == 10


def test_incidence_message_is_preserved_rather_than_looking_like_no_data() -> None:
    summary = parse_incidence("No observation time found in the database")

    assert summary.rows == []
    assert summary.note == "No observation time found in the database"


def test_incidence_parses_overall_and_stratified_rows() -> None:
    payload = [
        {"stratum": "Overall", "stratumName": "Overall", "persons": 100, "events": 10,
         "personYears": 1000.0, "incidenceRatePer1000PersonYears": 10.0},
        {"stratum": "Age", "stratumName": "70-79", "persons": 20, "events": 5,
         "personYears": 100.0, "incidenceRatePer1000PersonYears": 50.0},
        {"stratum": "Sex", "stratumName": "FEMALE", "persons": 50, "events": 4,
         "personYears": 500.0, "incidenceRatePer1000PersonYears": 8.0},
    ]

    summary = parse_incidence(payload)

    assert [row.stratum for row in summary.rows] == ["Overall", "Age", "Sex"]


class _RecordingClient:
    """Stands in for the MCP client, returning `capr`-only rows like the R tool does."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = known
        self.requests: list[list[str]] = []

    def list_tools(self):
        from phenotyping_agent.mcp_tools import EXPECTED_TOOLS

        return set(EXPECTED_TOOLS)

    def call_tool(self, name, args):
        requested = args["conceptSetNames"]
        self.requests.append(list(requested))
        # The R tool preserves input order but silently omits names it cannot find,
        # and returns no name column at all.
        return [{"capr": self.known[n], "conditionPersons": 1} for n in requested if n in self.known]


def _facade(run_id: str, known: dict[str, str]) -> tuple[ToolFacade, _RecordingClient]:
    facade = ToolFacade(make_config(run_id))
    client = _RecordingClient(known)
    facade.client = client  # type: ignore[assignment]
    return facade, client


def test_snippets_map_positionally_when_every_name_resolves() -> None:
    known = {"A": 'cs(concept(1), name = "A")', "B": 'cs(concept(2), name = "B")'}
    facade, client = _facade("test_shapes_ok", known)

    registry, gaps = facade.fetch_concept_set_snippets("p", ["A", "B"])

    assert registry == known and gaps == []
    assert len(client.requests) == 1, "the fast path should use a single batched call"


def test_an_unknown_name_never_shifts_snippets_onto_the_wrong_names() -> None:
    """The failure this guards: 'B' silently receiving C's concept IDs."""
    known = {"A": 'cs(concept(1), name = "A")', "C": 'cs(concept(3), name = "C")'}
    facade, _ = _facade("test_shapes_shift", known)

    registry, gaps = facade.fetch_concept_set_snippets("p", ["A", "B", "C"])

    assert gaps == ["B"]
    assert registry["A"] == known["A"]
    assert registry["C"] == known["C"]
    assert "B" not in registry


def test_all_names_unknown_yields_gaps_not_a_corrupt_registry() -> None:
    facade, _ = _facade("test_shapes_none", {})

    registry, gaps = facade.fetch_concept_set_snippets("p", ["X", "Y"])

    assert registry == {}
    assert gaps == ["X", "Y"]

