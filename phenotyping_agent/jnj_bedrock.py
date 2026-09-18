"""LangChain chat model for the J&J API-key-authenticated Bedrock gateway."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import SecretStr


class JnjBedrockChat(BaseChatModel):
    """Claude chat model exposed through J&J's Bedrock ``/model/.../invoke`` API."""

    model: str
    api_key: SecretStr
    base_url: str = "https://genai.jnj.com"
    anthropic_version: str = "bedrock-2023-05-31"
    max_tokens: int = 32000
    # Newer Claude deployments reject deprecated sampling parameters. Keep these opt-in.
    temperature: float | None = None
    top_p: float | None = None
    timeout: float = 120.0

    @property
    def _llm_type(self) -> str:
        return "jnj-bedrock"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url}

    @property
    def endpoint_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/model/{quote(self.model, safe='')}/invoke"

    def model_post_init(self, context: Any, /) -> None:
        super().model_post_init(context)
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BEDROCK_BASE_URL must be a valid HTTP(S) URL.")
        if not self.model.strip():
            raise ValueError("The J&J Bedrock model ID must not be empty.")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("BEDROCK_API_KEY must not be empty.")
        if not self.anthropic_version.strip():
            raise ValueError("BEDROCK_ANTHROPIC_VERSION must not be empty.")

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Any:
        anthropic_tools = []
        for tool in tools:
            converted = convert_to_openai_tool(tool)["function"]
            anthropic_tools.append(
                {
                    "name": converted["name"],
                    "description": converted.get("description", ""),
                    "input_schema": converted.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return self.bind(tools=anthropic_tools, tool_choice=tool_choice, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        body = self._request_body(messages, stop=stop, **kwargs)
        request = Request(
            self.endpoint_url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "x-api-key": self.api_key.get_secret_value(),
                "content-type": "application/json",
                "accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - configured HTTPS endpoint
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"J&J Bedrock gateway returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach J&J Bedrock gateway: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("J&J Bedrock gateway returned invalid JSON.") from exc

        if not isinstance(payload, Mapping):
            raise RuntimeError("J&J Bedrock gateway returned a non-object JSON response.")
        return ChatResult(generations=[ChatGeneration(message=self._response_message(payload))])

    def _request_body(
        self,
        messages: Sequence[BaseMessage],
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_parts: list[Any] = []
        turns: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                if isinstance(message.content, str):
                    system_parts.append(message.content)
                else:
                    system_parts.extend(message.content)
                continue
            if isinstance(message, ToolMessage):
                content: Any = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                    }
                ]
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
                content = self._assistant_content(message)
            elif isinstance(message, HumanMessage):
                role = "user"
                content = message.content
            else:
                role = "assistant" if message.type == "ai" else "user"
                content = message.content
            turns.append({"role": role, "content": content})

        body: dict[str, Any] = {
            "anthropic_version": self.anthropic_version,
            "max_tokens": self.max_tokens,
            "messages": turns,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts) if all(
                isinstance(part, str) for part in system_parts
            ) else system_parts
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if stop:
            body["stop_sequences"] = stop
        if tools := kwargs.get("tools"):
            body["tools"] = tools
        if tool_choice := kwargs.get("tool_choice"):
            body["tool_choice"] = self._tool_choice(tool_choice)
        return body

    @staticmethod
    def _assistant_content(message: AIMessage) -> Any:
        if isinstance(message.content, list):
            content = list(message.content)
        elif message.content:
            content = [{"type": "text", "text": str(message.content)}]
        else:
            content = []
        present_ids = {
            block.get("id") for block in content if isinstance(block, Mapping) and block.get("type") == "tool_use"
        }
        for call in message.tool_calls:
            if call.get("id") not in present_ids:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id"),
                        "name": call["name"],
                        "input": call.get("args", {}),
                    }
                )
        return content

    @staticmethod
    def _tool_choice(choice: Any) -> dict[str, Any]:
        if isinstance(choice, Mapping):
            return dict(choice)
        if choice in {"any", "required"}:
            return {"type": "any"}
        if choice in {"auto", "none"}:
            return {"type": choice}
        return {"type": "tool", "name": str(choice)}

    @staticmethod
    def _response_message(payload: Mapping[str, Any]) -> AIMessage:
        blocks = payload.get("content", [])
        if not isinstance(blocks, list):
            raise RuntimeError("J&J Bedrock response field 'content' must be a list.")
        tool_calls = [
            {
                "name": block.get("name", ""),
                "args": block.get("input", {}),
                "id": block.get("id"),
                "type": "tool_call",
            }
            for block in blocks
            if isinstance(block, Mapping) and block.get("type") == "tool_use"
        ]
        usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        return AIMessage(
            content=blocks,
            tool_calls=tool_calls,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            response_metadata={
                "finish_reason": payload.get("stop_reason"),
                "model": payload.get("model"),
                "response_id": payload.get("id"),
            },
        )


