You are writing the narrative section of the final report for an unattended phenotype
development run. The report's other sections (final Capr code, ledger tables, metric tables) are
generated deterministically and appended after your text; do not reproduce them.

Write markdown covering, in this order:

1. **What the final definition does**, in clinical language a domain expert can check without
   reading code.
2. **How it got there** - the arc across iterations: what each substantive change was trying to
   fix, and whether it worked. Use the ledger, not guesswork.
3. **Evidence quality** - the tally of expectation verdicts. If most expectations were graded
   `uninformative`, say plainly that the pre-registration provided little evidence in this run
   and that the prompts or the expectations need work. Do not paper over it.
4. **Validation results** - KEEPER metrics if available, and what the residual false positives
   and false negatives are likely to be, by mechanism.
5. **Limitations and unresolved gaps** - concept sets that could not be found, criteria in the
   clinical definition that could not be expressed, and anything the budgets cut short.
6. **Recommended next steps** for a human reviewer.

Rules: never present a number that did not come from a tool result. Never present an invented
epidemiologic benchmark as if it were literature-derived. Be concise and specific.


