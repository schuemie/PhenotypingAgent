from phenotyping_agent.capr_checks import validate_capr_static


def test_capr_static_rejects_unknown_concept_id() -> None:
    registry = {"ALF": 'cs(concept(12345), name = "Acute liver failure")'}
    capr = 'cohort(entry = entry(conditionOccurrence(cs(concept(999), name = "X"))))'
    errors = validate_capr_static(capr, registry)
    assert any("Unexpected concept IDs" in error for error in errors)


def test_capr_static_accepts_known_concepts() -> None:
    registry = {
        "ALF": 'cs(concept(12345), name = "Acute liver failure")',
        "CLD": 'cs(concept(22222), name = "Chronic liver disease")',
    }
    capr = (
        'cohort('\
        'entry = entry(conditionOccurrence(cs(concept(12345), name = "Acute liver failure"))), '\
        'attrition = attrition(inclusionRule(name = "x", expression = not(conditionOccurrence(cs(concept(22222), name = "Chronic liver disease"), duringInterval(-365, -1)))))'\
        ')'
    )
    errors = validate_capr_static(capr, registry)
    assert errors == []

