from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, SecretStr

from phenotyping_agent.config import ModelTier
from phenotyping_agent.jnj_bedrock import JnjBedrockChat
from phenotyping_agent.llm_client import MAX_OUTPUT_TOKENS, get_llm_client


class _FakeBedrockClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _clear_custom_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
    monkeypatch.delenv("BEDROCK_BASE_URL", raising=False)
    monkeypatch.delenv("BEDROCK_ANTHROPIC_VERSION", raising=False)


def test_bedrock_requires_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_aws", SimpleNamespace(ChatBedrockConverse=_FakeBedrockClient))
    monkeypatch.delenv("BEDROCK_AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    with pytest.raises(ValueError, match="Bedrock region"):
        get_llm_client(ModelTier(provider="bedrock", model="anthropic.claude-3-opus-20240229-v1:0"))


def test_bedrock_builds_client_from_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_aws", SimpleNamespace(ChatBedrockConverse=_FakeBedrockClient))
    monkeypatch.setenv("BEDROCK_AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_AWS_PROFILE", "clinical-ai")

    client = get_llm_client(
        ModelTier(provider="bedrock", model="anthropic.claude-3-opus-20240229-v1:0")
    )

    assert isinstance(client, _FakeBedrockClient)
    assert client.kwargs == {
        "model": "anthropic.claude-3-opus-20240229-v1:0",
        "region_name": "us-east-1",
        "credentials_profile_name": "clinical-ai",
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.2,
        "top_p": 0.9,
    }


def test_bedrock_explicit_credentials_must_be_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_aws", SimpleNamespace(ChatBedrockConverse=_FakeBedrockClient))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(ValueError, match="AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"):
        get_llm_client(ModelTier(provider="bedrock", model="anthropic.claude-3-opus-20240229-v1:0"))


def test_custom_bedrock_gateway_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_BASE_URL", "https://gateway.example")

    with pytest.raises(ValueError, match="BEDROCK_API_KEY"):
        get_llm_client(ModelTier(provider="bedrock", model="anthropic.claude-v2:1"))


def test_custom_bedrock_gateway_does_not_require_aws_or_langchain_aws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEDROCK_API_KEY", "secret-key")
    monkeypatch.setenv("BEDROCK_ANTHROPIC_VERSION", "custom-version")
    monkeypatch.delenv("BEDROCK_AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setitem(sys.modules, "langchain_aws", None)

    client = get_llm_client(
        ModelTier(provider="bedrock", model="us.anthropic.claude-sonnet-4-20250514-v1:0")
    )

    assert isinstance(client, JnjBedrockChat)
    assert client.base_url == "https://genaiapigwna.jnj.com"
    assert client.anthropic_version == "custom-version"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_custom_bedrock_gateway_translates_request_and_tool_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "id": "msg-1",
                "model": "claude",
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 12, "output_tokens": 4},
                "content": [
                    {"type": "text", "text": "I'll check."},
                    {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {"q": "ALF"}},
                ],
            }
        )

    monkeypatch.setattr("phenotyping_agent.jnj_bedrock.urlopen", fake_urlopen)
    client = JnjBedrockChat(
        model="us.anthropic/claude:1",
        api_key=SecretStr("secret-key"),
        base_url="https://gateway.example/",
        anthropic_version="bedrock-test",
        max_tokens=123,
    ).bind_tools(
        [{"name": "lookup", "description": "Look up a term", "parameters": {"type": "object"}}]
    )

    response = client.invoke(
        [SystemMessage(content="Be precise."), HumanMessage(content="Check ALF")]
    )

    request = captured["request"]
    body = json.loads(request.data)
    assert request.full_url == "https://gateway.example/model/us.anthropic%2Fclaude%3A1/invoke"
    assert request.get_header("X-api-key") == "secret-key"
    assert body["anthropic_version"] == "bedrock-test"
    assert body["max_tokens"] == 123
    assert body["system"] == "Be precise."
    assert body["messages"] == [{"role": "user", "content": "Check ALF"}]
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    assert "model" not in body and "stream" not in body
    assert "temperature" not in body and "top_p" not in body
    assert response.tool_calls == [
        {"name": "lookup", "args": {"q": "ALF"}, "id": "tool-1", "type": "tool_call"}
    ]
    assert response.usage_metadata == {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}


def test_custom_bedrock_supports_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class Answer(BaseModel):
        value: int

    monkeypatch.setattr(
        "phenotyping_agent.jnj_bedrock.urlopen",
        lambda request, timeout: _FakeResponse(
            {
                "stop_reason": "tool_use",
                "content": [
                    {"type": "tool_use", "id": "answer-1", "name": "Answer", "input": {"value": 7}}
                ],
            }
        ),
    )
    client = JnjBedrockChat(
        model="anthropic.claude-v2:1", api_key=SecretStr("secret-key")
    )

    result = client.with_structured_output(Answer, include_raw=True).invoke("Answer now")

    assert result["parsed"] == Answer(value=7)
    assert result["parsing_error"] is None


