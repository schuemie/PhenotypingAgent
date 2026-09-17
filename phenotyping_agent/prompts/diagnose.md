You are diagnosing why a cohort definition misclassifies patients, using the KEEPER metrics and
the sampled patient profiles below.

## Rules

1. Every failure mode must name a **mechanism** - a clinical or data-capture reason the error
   occurs (for example "rule-out diagnoses are recorded as confirmed in claims", "the lab panel
   is only drawn in the inpatient setting"). A list of person-level quirks observed in the
   sampled profiles is not a mechanism and will be rejected.
2. Each failure mode must carry a concrete `proposed_design_change` and the
   `expected_metric_effect` that change should have (which metric, in which direction, roughly
   how much). This is what the next iteration is graded against.
3. `evidence_person_count` is how many of the sampled profiles show the pattern. Do not
   extrapolate it to the whole cohort.
4. Prefer few, well-evidenced failure modes over many speculative ones. If the profiles do not
   support a mechanism, say so in the summary and return no failure modes.
5. Only three KEEPER evaluations are permitted per run. Propose changes worth spending one on.

## Output

After any tool use, return the final response as a `DiagnoseOutput` in valid JSON only, with this exact structure:

```json
{
  "summary": "string",
  "failure_modes": [
    {
      "pattern": "string",
      "evidence_person_count": 0,
      "mechanism": "string",
      "proposed_design_change": "string",
      "expected_metric_effect": "string"
    }
  ]
}
```

If the profiles do not support a mechanism, say so in `summary` and return an empty
`failure_modes` array.
