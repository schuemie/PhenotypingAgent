"""Tests for the structured-output retry/repair behaviour of `LLMRuntime`."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from phenotyping_agent.config import ModelTier
from phenotyping_agent.llm_runtime import LLMRuntime, StubbedTierError
from helpers import make_config


class _Answer(BaseModel):
    value: int


class _FakeStructuredRunnable:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        return self.results.pop(0)


class _FakeClient:
    def __init__(self, results: list[dict]) -> None:
        self.runnable = _FakeStructuredRunnable(results)

    def with_structured_output(self, schema, include_raw=False):
        return self.runnable


TIER = ModelTier(provider="openai", model="fake-model")


def _runtime(results: list[dict], run_id: str) -> tuple[LLMRuntime, _FakeClient]:
    runtime = LLMRuntime(make_config(run_id))
    client = _FakeClient(results)
    runtime._clients[(TIER.provider, TIER.model)] = client
    return runtime, client


def test_structured_retries_and_repairs_after_validation_error() -> None:
    runtime, client = _runtime(
        [
            {"raw": AIMessage(content="not json"), "parsed": None, "parsing_error": "missing value"},
            {"raw": AIMessage(content="{}"), "parsed": _Answer(value=7), "parsing_error": None},
        ],
        "test_runtime_retry",
    )

    result = runtime.structured(
        tier=TIER,
        node="unit",
        messages=[HumanMessage(content="go")],
        schema=_Answer,
    )

    assert isinstance(result, _Answer) and result.value == 7
    assert len(client.runnable.calls) == 2, "the failure should have triggered exactly one repair"
    repair_prompt = client.runnable.calls[1][-1].content
    assert "_Answer" in repair_prompt and "missing value" in repair_prompt


def test_structured_raises_once_retries_are_exhausted() -> None:
    failure = {"raw": AIMessage(content="junk"), "parsed": None, "parsing_error": "bad"}
    runtime, client = _runtime([dict(failure) for _ in range(3)], "test_runtime_exhausted")

    with pytest.raises(RuntimeError, match="structured output failed after retries"):
        runtime.structured(
            tier=TIER,
            node="unit",
            messages=[HumanMessage(content="go")],
            schema=_Answer,
            max_retries=2,
        )
    assert len(client.runnable.calls) == 3


def test_stubbed_tier_never_calls_a_model() -> None:
    runtime = LLMRuntime(make_config("test_runtime_stub"))
    none_tier = ModelTier(provider="none", model="dry-run")

    assert runtime.structured(
        tier=none_tier,
        node="unit",
        messages=[],
        schema=_Answer,
        stub=lambda: _Answer(value=1),
    ) == _Answer(value=1)

    with pytest.raises(StubbedTierError):
        runtime.structured(tier=none_tier, node="unit", messages=[], schema=_Answer)


def test_llm_events_are_logged() -> None:
    runtime, _ = _runtime(
        [{"raw": AIMessage(content="{}"), "parsed": _Answer(value=1), "parsing_error": None}],
        "test_runtime_events",
    )
    runtime.event_logger.path.unlink(missing_ok=True)

    runtime.structured(
        tier=TIER, node="unit", messages=[HumanMessage(content="go")], schema=_Answer
    )

    lines = runtime.event_logger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and '"node": "unit"' in lines[0]

