from __future__ import annotations

import json
from pathlib import Path

import pytest

from phenotyping_agent.config import ModelTier
from phenotyping_agent.llm_client import invoke_with_logging
from phenotyping_agent.llm_events import LLMEventLogger


class _FakeResponse:
    def __init__(self) -> None:
        self.content = "Structured cohort draft"
        self.usage_metadata = {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
        }
        self.response_metadata = {"finish_reason": "stop"}


class _FakeClient:
    def invoke(self, messages):
        return _FakeResponse()


class _FailingClient:
    def invoke(self, messages):
        raise RuntimeError("upstream timeout")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_llm_event_logger_appends_jsonl_lines(tmp_path: Path) -> None:
    logger = LLMEventLogger(tmp_path)
    logger.append({"event": "llm_response", "request_id": "r1", "node": "design"})
    logger.append({"event": "llm_response", "request_id": "r2", "node": "assess"})

    events = _read_jsonl(tmp_path / "llm_events.jsonl")
    assert len(events) == 2
    assert events[0]["request_id"] == "r1"
    assert events[1]["request_id"] == "r2"


def test_invoke_with_logging_writes_response_event(tmp_path: Path) -> None:
    logger = LLMEventLogger(tmp_path)
    client = _FakeClient()
    tier = ModelTier(provider="openai", model="o3")

    response = invoke_with_logging(
        client,
        [("system", "You are a cohort assistant."), ("human", "Draft inclusion criteria")],
        event_logger=logger,
        tier=tier,
        node="design",
        prompt_template="prompts/design.md",
        metadata={"iteration": 1},
    )

    assert isinstance(response, _FakeResponse)

    events = _read_jsonl(tmp_path / "llm_events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "llm_response"
    assert event["model"] == "o3"
    assert event["node"] == "design"
    assert event["prompt_template"] == "prompts/design.md"
    assert event["output_text"] == "Structured cohort draft"
    assert event["usage"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert event["finish_reason"] == "stop"
    assert event["error"] is None


def test_invoke_with_logging_writes_error_event(tmp_path: Path) -> None:
    logger = LLMEventLogger(tmp_path)
    tier = ModelTier(provider="openai", model="o3")

    with pytest.raises(RuntimeError, match="upstream timeout"):
        invoke_with_logging(
            _FailingClient(),
            [("human", "test")],
            event_logger=logger,
            tier=tier,
            node="design",
        )

    events = _read_jsonl(tmp_path / "llm_events.jsonl")
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "llm_error"
    assert event["error"] == "upstream timeout"

