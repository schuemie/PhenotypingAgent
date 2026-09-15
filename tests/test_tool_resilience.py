"""Resilience behaviour of the tool facade: retries, timeouts and budget accounting."""

from __future__ import annotations

import pytest

from phenotyping_agent.mcp_tools import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    EXPECTED_TOOLS,
    NON_RETRYABLE_TOOLS,
    TOOL_TIMEOUT_SECONDS,
    McpToolError,
    ToolFacade,
)
from phenotyping_agent.state import Expectation
from helpers import make_config


class _FlakyClient:
    def __init__(self, failures: int, error: Exception) -> None:
        self.failures = failures
        self.error = error
        self.attempts: list[str] = []

    def list_tools(self):
        return set(EXPECTED_TOOLS)

    def call_tool(self, name, args):
        self.attempts.append(name)
        if self.failures > 0:
            self.failures -= 1
            raise self.error
        return [{"sensitivity": 0.9, "specificity": 0.9, "ppv": 0.9, "tp": 1, "fp": 1, "tn": 1, "fn": 1}]


def _facade(run_id: str, client) -> ToolFacade:
    facade = ToolFacade(make_config(run_id))
    facade.client = client  # type: ignore[assignment]
    return facade


def _keeper_expectation() -> Expectation:
    return Expectation(
        diagnostic="keeperMetrics",
        target="overall",
        claim_kind="direction",
        claim="PPV above 0.8",
        would_falsify="PPV below 0.8",
        rationale="threshold",
        basis="supplied_by_user",
    )


def test_transport_errors_are_retried_once() -> None:
    client = _FlakyClient(failures=1, error=ConnectionError("socket closed"))
    facade = _facade("test_retry_transport", client)

    result = facade.convert_capr_to_json("cohort()")

    assert len(client.attempts) == 2
    assert result


def test_server_side_tool_errors_are_not_retried() -> None:
    client = _FlakyClient(failures=1, error=McpToolError("MCP tool failed: bad Capr"))
    facade = _facade("test_retry_toolerror", client)

    with pytest.raises(McpToolError):
        facade.convert_capr_to_json("cohort()")
    assert len(client.attempts) == 1, "the server already ran it; retrying just wastes time"


def test_expensive_tools_are_never_retried() -> None:
    client = _FlakyClient(failures=1, error=ConnectionError("socket closed"))
    facade = _facade("test_retry_expensive", client)

    with pytest.raises(ConnectionError):
        facade.generate_cohort("cohort()")
    assert len(client.attempts) == 1
    assert "generateCohort" in NON_RETRYABLE_TOOLS


def test_a_failed_evaluation_does_not_consume_the_keeper_budget() -> None:
    client = _FlakyClient(failures=1, error=McpToolError("No reference cohort for this phenotype"))
    facade = _facade("test_budget_not_burned", client)
    facade.record_expectation(_keeper_expectation())

    with pytest.raises(McpToolError):
        facade.evaluate_cohort(101, "Some phenotype")

    assert facade.budget.evaluate_calls_used == 0, (
        "a phenotype with no reference cohort must not cost one of only three evaluations"
    )


def test_successful_evaluations_consume_the_budget_and_then_hard_stop() -> None:
    client = _FlakyClient(failures=0, error=RuntimeError("unused"))
    facade = _facade("test_budget_enforced", client)
    budget = facade.config.budgets.evaluate_calls

    for _ in range(budget):
        facade.record_expectation(_keeper_expectation())
        facade.evaluate_cohort(101, "Acute liver failure")

    assert facade.budget.evaluate_calls_used == budget
    facade.record_expectation(_keeper_expectation())
    with pytest.raises(RuntimeError, match="budget exhausted"):
        facade.evaluate_cohort(101, "Acute liver failure")


def test_long_running_tools_get_generous_timeouts() -> None:
    assert TOOL_TIMEOUT_SECONDS["generateCohort"] > DEFAULT_TOOL_TIMEOUT_SECONDS
    assert TOOL_TIMEOUT_SECONDS["evaluateCohort"] > DEFAULT_TOOL_TIMEOUT_SECONDS
    assert all(seconds > 0 for seconds in TOOL_TIMEOUT_SECONDS.values())

