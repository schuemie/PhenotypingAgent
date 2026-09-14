from __future__ import annotations

import re


def extract_concept_ids(text: str) -> set[int]:
    return {int(match) for match in re.findall(r"concept\((\d+)\)", text)}


def validate_capr_static(capr_code: str, concept_set_registry: dict[str, str]) -> list[str]:
    errors: list[str] = []
    stripped = capr_code.strip()
    if stripped.count("cohort(") != 1:
        errors.append("Capr code must contain exactly one top-level cohort( expression")
    first_line = stripped.splitlines()[0] if stripped else ""
    if "<-" in first_line or "=" in first_line.split("cohort(")[0]:
        errors.append("Top-level assignments are not allowed")

    allowed_ids: set[int] = set()
    for snippet in concept_set_registry.values():
        allowed_ids.update(extract_concept_ids(snippet))
    code_ids = extract_concept_ids(capr_code)
    unexpected = sorted(code_ids - allowed_ids)
    if unexpected:
        errors.append(f"Unexpected concept IDs not in registry: {unexpected}")
    return errors


