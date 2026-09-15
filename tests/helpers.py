"""Shared test helpers: a scripted LLM runtime and a ready-made `NodeDeps`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from phenotyping_agent.config import AppConfig, build_config
from phenotyping_agent.deps import BudgetGuard, NodeDeps
from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.llm_runtime import LLMRuntime
from phenotyping_agent.mcp_tools import ToolFacade

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ScriptedRuntime(LLMRuntime):
    """An `LLMRuntime` that replays queued responses instead of calling a model.

    Each queue is consumed in order; a callable entry is invoked with the messages so a test can
    assert on prompt content or raise.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        structured: Sequence[Any] = (),
        text: Sequence[Any] = (),
        chat: Sequence[Any] = (),
    ) -> None:
        super().__init__(config)
        self.structured_queue = list(structured)
        self.text_queue = list(text)
        self.chat_queue = list(chat)
        self.calls: list[tuple[str, str]] = []  # (kind, node)
        self.messages_seen: list[list[BaseMessage]] = []

    def _next(self, queue: list[Any], messages: Sequence[BaseMessage], kind: str) -> Any:
        self.messages_seen.append(list(messages))
        if not queue:
            raise AssertionError(f"ScriptedRuntime ran out of queued {kind} responses")
        item = queue.pop(0)
        return item(messages) if callable(item) else item

    def structured(self, *, tier, node, messages, schema, **kwargs) -> BaseModel:  # type: ignore[override]
        self.calls.append(("structured", node))
        return self._next(self.structured_queue, messages, "structured")

    def text(self, *, tier, node, messages, **kwargs) -> str:  # type: ignore[override]
        self.calls.append(("text", node))
        return self._next(self.text_queue, messages, "text")

    def chat(self, *, tier, node, messages, **kwargs) -> AIMessage:  # type: ignore[override]
        self.calls.append(("chat", node))
        if not self.chat_queue:
            return AIMessage(content="")
        return self._next(self.chat_queue, messages, "chat")


def make_config(run_id: str, **overrides: Any) -> AppConfig:
    return build_config(
        project_root=PROJECT_ROOT,
        clinical_definition_path=PROJECT_ROOT / "acute liver failure.txt",
        phenotype="Acute liver failure",
        dry_run=True,
        run_id=run_id,
        **overrides,
    )


def make_deps(run_id: str, runtime_factory: Callable[[AppConfig], LLMRuntime] | None = None) -> NodeDeps:
    config = make_config(run_id)
    runtime = runtime_factory(config) if runtime_factory else LLMRuntime(config)
    return NodeDeps(
        config=config,
        tools=ToolFacade(config),
        runtime=runtime,
        ledger_store=LedgerStore(config.runs_dir),
        budget_guard=BudgetGuard(wall_clock_minutes=config.budgets.wall_clock_minutes),
    )

