"""Runtime wrapper that turns configured model tiers into usable, logged LLM calls.

Three call styles are offered:

- :meth:`LLMRuntime.structured` - pydantic-validated output with automatic repair retries.
- :meth:`LLMRuntime.text` - free prose (used by ``report``).
- :meth:`LLMRuntime.chat` - raw chat turn with optional bound tools (used by the ``design``
  tool sub-loop).

When a tier has ``provider == "none"`` (the dry-run default) no network call is made and the
caller-supplied ``stub`` factory is used instead. That keeps ``--dry-run`` fully offline while
leaving node code identical in both modes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from phenotyping_agent.config import AppConfig, ModelTier
from phenotyping_agent.llm_events import LLMEventLogger, extract_text, extract_usage
from phenotyping_agent.llm_client import get_llm_client

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a node prompt from ``phenotyping_agent/prompts/<name>.md``."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


class StubbedTierError(RuntimeError):
    """Raised when a stubbed tier is used without a stub factory."""


class LLMRuntime:
    def __init__(self, config: AppConfig, event_logger: LLMEventLogger | None = None) -> None:
        """Initialize the LLM runtime.

        Args:
            config: Application configuration containing model tier settings and paths.
            event_logger: Optional LLM event logger. If not provided, creates a new one
                using the runs directory from config.
        """
        self.config = config
        self.event_logger = event_logger or LLMEventLogger(config.runs_dir)
        self._clients: dict[tuple[str, str], Any] = {}
        self.total_tokens = 0

    # ------------------------------------------------------------------ tiers
    @property
    def reasoning(self) -> ModelTier:
        """Get the reasoning model tier (slower, more capable).

        Returns:
            The configured reasoning tier for complex reasoning tasks.
        """
        return self.config.reasoning_tier

    @property
    def fast(self) -> ModelTier:
        """Get the fast model tier (faster, lighter weight).

        Returns:
            The configured fast tier for quick, simple tasks.
        """
        return self.config.fast_tier

    @staticmethod
    def is_stubbed(tier: ModelTier) -> bool:
        """Check if a model tier is stubbed (running in dry-run mode).

        Args:
            tier: The model tier to check.

        Returns:
            True if the tier has provider == "none", indicating dry-run/test mode.
        """
        return tier.provider == "none"

    def client(self, tier: ModelTier) -> Any:
        """Get or create a cached LLM client for the given tier.

        Clients are cached by (provider, model) key to avoid repeated instantiation.

        Args:
            tier: The model tier configuration.

        Returns:
            An instantiated LLM client (ChatOpenAI, AzureChatOpenAI, or ChatAnthropic).

        Raises:
            ValueError: If required environment variables are missing or provider is invalid.
            ImportError: If required dependencies are not installed.
        """
        key = (tier.provider, tier.model)
        if key not in self._clients:
            self._clients[key] = get_llm_client(tier)
        return self._clients[key]

    # ------------------------------------------------------------- invocation
    def _invoke(
        self,
        runnable: Any,
        messages: Sequence[BaseMessage],
        *,
        tier: ModelTier,
        node: str,
        prompt_template: str | None,
        metadata: dict[str, Any] | None,
        raw_of: Callable[[Any], Any] = lambda value: value,
    ) -> Any:
        request_id = str(uuid4())
        started = time.perf_counter()
        base = {
            "event": "llm_response",
            "request_id": request_id,
            "provider": tier.provider,
            "model": tier.model,
            "node": node,
            "prompt_template": prompt_template,
            "metadata": metadata or {},
            "input_text": extract_text(list(messages)),
        }
        try:
            response = runnable.invoke(list(messages))
        except Exception as exc:  # noqa: BLE001 - logged then re-raised
            self.event_logger.append(
                {
                    **base,
                    "event": "llm_error",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "error": str(exc),
                }
            )
            raise

        raw = raw_of(response)
        usage = extract_usage(raw)
        if usage:
            self.total_tokens += int(usage.get("total_tokens", 0) or 0)
        response_metadata = getattr(raw, "response_metadata", None)
        finish_reason = (
            response_metadata.get("finish_reason") if isinstance(response_metadata, dict) else None
        )
        self.event_logger.append(
            {
                **base,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "output_text": extract_text(raw),
                "usage": usage,
                "finish_reason": finish_reason,
                "error": None,
            }
        )
        return response

    # ------------------------------------------------------------------- APIs
    def structured(
        self,
        *,
        tier: ModelTier,
        node: str,
        messages: Sequence[BaseMessage],
        schema: type[BaseModel],
        prompt_template: str | None = None,
        stub: Callable[[], BaseModel] | None = None,
        max_retries: int = 2,
        metadata: dict[str, Any] | None = None,
    ) -> BaseModel:
        """Invoke the model and return a Pydantic-validated structured output instance.

        If the LLM fails to produce valid structured output, the error is fed back
        to the model as a repair turn, retrying up to ``max_retries`` times before
        raising. This provides a self-healing mechanism for JSON parsing and validation.

        Args:
            tier: The model tier to use for this call.
            node: Name of the workflow node making this call (for logging).
            messages: Sequence of chat messages for the LLM.
            schema: The Pydantic BaseModel class that the output must conform to.
            prompt_template: Optional prompt template identifier for logging.
            stub: Optional factory function for dry-run mode (provider == "none").
            max_retries: Maximum number of repair attempts before giving up (default: 2).
            metadata: Optional custom metadata to include in logs.

        Returns:
            A validated instance of the schema class.

        Raises:
            StubbedTierError: If tier is stubbed and no stub is provided.
            RuntimeError: If structured output fails after all retry attempts.
        """
        if self.is_stubbed(tier):
            return self._stub_value(node, stub)

        runnable = self.client(tier).with_structured_output(schema, include_raw=True)
        turns = list(messages)
        last_error = "unknown parsing failure"
        for attempt in range(max_retries + 1):
            try:
                result = self._invoke(
                    runnable,
                    turns,
                    tier=tier,
                    node=node,
                    prompt_template=prompt_template,
                    metadata={**(metadata or {}), "schema": schema.__name__, "attempt": attempt},
                    raw_of=lambda value: value.get("raw") if isinstance(value, dict) else value,
                )
            except Exception as exc:  # noqa: BLE001 - fed back to the model for repair
                last_error = str(exc)
                turns = [
                    *turns,
                    AIMessage(content=f"Structured output was rejected: {last_error}"),
                    HumanMessage(
                        content=(
                            "Your previous response did not satisfy the required schema "
                            f"`{schema.__name__}`. Error:\n{last_error}\n"
                            "Return a corrected response that satisfies the schema exactly."
                        )
                    ),
                ]
                continue
            parsed = result.get("parsed") if isinstance(result, dict) else result
            error = result.get("parsing_error") if isinstance(result, dict) else None
            if isinstance(parsed, schema) and error is None:
                return parsed
            last_error = str(error or "model returned no parseable structured output")
            raw = result.get("raw") if isinstance(result, dict) else None
            turns = [
                *turns,
                raw if isinstance(raw, AIMessage) else AIMessage(content=extract_text(raw)),
                HumanMessage(
                    content=(
                        "Your previous response did not satisfy the required schema "
                        f"`{schema.__name__}`. Error:\n{last_error}\n"
                        "Return a corrected response that satisfies the schema exactly."
                    )
                ),
            ]
        raise RuntimeError(f"[{node}] structured output failed after retries: {last_error}")

    def text(
        self,
        *,
        tier: ModelTier,
        node: str,
        messages: Sequence[BaseMessage],
        prompt_template: str | None = None,
        stub: Callable[[], str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Invoke the model and return free-form text output.

        Use this for unstructured responses like report generation or natural language
        output where JSON validation is not needed.

        Args:
            tier: The model tier to use for this call.
            node: Name of the workflow node making this call (for logging).
            messages: Sequence of chat messages for the LLM.
            prompt_template: Optional prompt template identifier for logging.
            stub: Optional factory function for dry-run mode (provider == "none").
            metadata: Optional custom metadata to include in logs.

        Returns:
            The LLM's text response as a string.

        Raises:
            StubbedTierError: If tier is stubbed and no stub is provided.
        """
        if self.is_stubbed(tier):
            return self._stub_value(node, stub)
        response = self._invoke(
            self.client(tier),
            messages,
            tier=tier,
            node=node,
            prompt_template=prompt_template,
            metadata=metadata,
        )
        return extract_text(response)

    def chat(
        self,
        *,
        tier: ModelTier,
        node: str,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any] | None = None,
        prompt_template: str | None = None,
        stub: Callable[[], AIMessage] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AIMessage:
        """Invoke the model in a raw chat turn with optional tool binding.

        Use this for interactive conversation flows where the LLM may call tools
        and the response is an AIMessage that may contain tool calls.

        Args:
            tier: The model tier to use for this call.
            node: Name of the workflow node making this call (for logging).
            messages: Sequence of chat messages for the LLM.
            tools: Optional sequence of tool definitions to bind to the model.
            prompt_template: Optional prompt template identifier for logging.
            stub: Optional factory function for dry-run mode (provider == "none").
            metadata: Optional custom metadata to include in logs.

        Returns:
            An AIMessage from the LLM, potentially containing tool calls.

        Raises:
            StubbedTierError: If tier is stubbed and no stub is provided.
        """
        if self.is_stubbed(tier):
            return self._stub_value(node, stub)
        runnable = self.client(tier)
        if tools:
            runnable = runnable.bind_tools(list(tools))
        return self._invoke(
            runnable,
            messages,
            tier=tier,
            node=node,
            prompt_template=prompt_template,
            metadata=metadata,
        )

    # ----------------------------------------------------------------- stubs
    @staticmethod
    def _stub_value(node: str, stub: Callable[[], Any] | None) -> Any:
        if stub is None:
            raise StubbedTierError(
                f"Node '{node}' requires an LLM but the tier provider is 'none' and no stub "
                "was supplied. Configure a provider/model or run with --dry-run."
            )
        return stub()


