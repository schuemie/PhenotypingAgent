"""Shared, non-serialisable dependencies handed to every graph node."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from phenotyping_agent.config import AppConfig
from phenotyping_agent.ledger import LedgerStore
from phenotyping_agent.llm_runtime import LLMRuntime
from phenotyping_agent.mcp_tools import ToolFacade


@dataclass(slots=True)
class BudgetGuard:
    """Wall-clock and token budget tracking, checked between nodes."""

    wall_clock_minutes: int
    max_total_tokens: int | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_minutes(self) -> float:
        return (time.monotonic() - self.started_at) / 60.0

    def exhausted(self, total_tokens: int = 0) -> str | None:
        if self.elapsed_minutes >= self.wall_clock_minutes:
            return (
                f"Wall-clock budget of {self.wall_clock_minutes} minutes exhausted "
                f"after {self.elapsed_minutes:.1f} minutes."
            )
        if self.max_total_tokens is not None and total_tokens >= self.max_total_tokens:
            return f"Token budget of {self.max_total_tokens} exhausted ({total_tokens} used)."
        return None


@dataclass(slots=True)
class NodeDeps:
    config: AppConfig
    tools: ToolFacade
    runtime: LLMRuntime
    ledger_store: LedgerStore
    budget_guard: BudgetGuard

    def budget_stop_reason(self) -> str | None:
        return self.budget_guard.exhausted(self.runtime.total_tokens)

