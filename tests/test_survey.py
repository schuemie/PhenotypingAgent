from phenotyping_agent.nodes.survey import _parse_table


def test_parse_table_supports_with_descendants_column() -> None:
    table = """
| conceptsetName | withDescendants | personCount |
|---|---|---|
| Acute liver failure | Y | 100 |
| Chronic liver disease | N | 42 |
""".strip()

    summaries = _parse_table(table)

    assert len(summaries) == 2
    assert summaries[0].concept_set_name == "Acute liver failure"
    assert summaries[0].with_descendants is True
    assert summaries[0].person_count == 100
    assert summaries[1].concept_set_name == "Chronic liver disease"
    assert summaries[1].with_descendants is False
    assert summaries[1].person_count == 42


