"""The `evaluate` node: Phase 3 KEEPER evaluation plus error-profile-driven profile sampling.

The three-evaluation cap is enforced by the tool wrapper, not by prompt compliance.
"""

from __future__ import annotations

from typing import Any

from phenotyping_agent.deps import NodeDeps
from phenotyping_agent.parsing import parse_keeper
from phenotyping_agent.state import AgentState, Expectation, KeeperMetrics

EVALUATE_TOOL_ALLOWLIST = {"evaluateCohort", "samplePatientProfile"}

_KEEPER_EXPECTATION = Expectation(
    diagnostic="keeperMetrics",
    target="overall",
    claim_kind="direction",
    claim="PPV and sensitivity should both exceed 0.8",
    would_falsify="PPV or sensitivity stays below 0.8 without an identifiable mechanism",
    rationale="Acceptance threshold from the cohort-developer skill.",
    basis="supplied_by_user",
)


def _sampling_plan(metrics: KeeperMetrics | None, limit: int) -> list[str]:
    """Deterministic sampling driven by the error profile (plan section 6)."""
    if metrics is None:
        return ["FP", "FN", "TP"][:limit]
    ppv_weak = metrics.ppv < 0.8
    sensitivity_weak = metrics.sensitivity < 0.8
    if ppv_weak and sensitivity_weak:
        plan = ["FP", "FP", "FP", "FN", "FN", "FN"]
    elif ppv_weak:
        plan = ["FP", "FP", "FP", "FP", "FP", "TP"]
    elif sensitivity_weak:
        plan = ["FN", "FN", "FN", "FN", "FN", "TP"]
    else:
        plan = ["FP", "FN", "TP"]
    return plan[:limit]


def run(state: AgentState, deps: NodeDeps) -> dict:
    cohort_id = state.get("current_cohort_id")
    if cohort_id is None:
        raise RuntimeError("Cannot evaluate without a cohort ID")

    facade = deps.tools
    facade.record_expectation(_KEEPER_EXPECTATION)

    with facade.restrict_to(EVALUATE_TOOL_ALLOWLIST):
        try:
            raw = facade.evaluate_cohort(cohort_id, state["phenotype"])
        except Exception as exc:  # noqa: BLE001
            # `getKeeperReferenceCohortId` only covers some phenotypes; report rather than crash.
            return {
                "next_action": "done",
                "stop_reason": (
                    "KEEPER evaluation is unavailable for this phenotype, so the run stops after "
                    f"Phase 2. Tool error: {exc}"
                ),
            }

        metrics = parse_keeper(raw)
        profiles: list[Any] = []
        for ptype in _sampling_plan(metrics, deps.config.budgets.sample_profiles_per_eval):
            try:
                profiles.append(facade.sample_patient_profile(cohort_id, state["phenotype"], ptype))
            except Exception as exc:  # noqa: BLE001 - sampling is best-effort
                profiles.append({"type": ptype, "patientProfile": "", "rationale": f"error: {exc}"})

    update: dict = {
        "latest_keeper": metrics,
        "latest_profiles": profiles,
        "evaluate_calls": facade.budget.evaluate_calls_used,
    }

    # Amend this iteration's ledger entry, which `assess` wrote before the evaluation ran.
    ledger = state.get("ledger", [])
    if ledger and metrics is not None:
        current = ledger[-1]
        amended = current.model_copy(update={"keeper": metrics})
        deps.ledger_store.append(amended)
        update["ledger"] = [amended]

    if metrics is not None and metrics.ppv >= 0.8 and metrics.sensitivity >= 0.8:
        update["next_action"] = "done"
        update["stop_reason"] = (
            f"Acceptance criteria met: PPV {metrics.ppv:.3f} and sensitivity "
            f"{metrics.sensitivity:.3f} both exceed 0.8."
        )

    return update
