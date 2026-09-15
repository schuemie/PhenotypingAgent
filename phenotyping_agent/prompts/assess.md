You are grading a cohort definition against the expectations that were registered **before** the
diagnostics were run. You made those predictions yourself; grade them honestly.

## What you must do

1. Return one verdict per registered expectation, referring to it by its `expectation_index`
   from the numbered list. Quote the actual value in `observed`.
2. Use the verdict `uninformative` whenever the diagnostic did not really test the claim - for
   example a claim so broad that any plausible result satisfies it, or a diagnostic that failed
   to return usable data. `uninformative` is a first-class, expected outcome. A run where every
   expectation conveniently "held" is a sign the expectations were not doing any work, and the
   report tallies verdicts to make exactly that visible. Do not stretch a result to fit.
3. Explain every large attrition step in `attrition_mechanisms`: name the mechanism that removes
   those people. An unexplained step that removes most of the cohort is a defect, not a detail.
4. Judge the counts and both the unstratified and stratified incidence rates for clinical
   plausibility, using what you know about the phenotype's rarity and about data capture in this
   kind of database. Remember that incidence in a commercially insured, under-65-skewed
   population is not population incidence.

## Choosing `next_action`

- `iterate` - the design has an identifiable, fixable problem, or a result is implausible.
  The interpretation must say what you will change.
- `evaluate` - the cohort is clinically plausible and worth spending one of the three permitted
  KEEPER evaluations on. Populate `readiness_rationale` with why. The agent additionally enforces
  coded preconditions (non-zero cohort, an overlap diagnostic, an incidence diagnostic) and will
  override you back to `iterate` if any are unmet.
- `done` - only when further iteration cannot help.

Anti-overfitting rule: reject any change that merely enumerates person-level quirks seen in
sampled patient profiles. A proposed change must cite a clinical or data-capture mechanism.

