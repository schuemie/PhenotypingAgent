from __future__ import annotations

import json
from pathlib import Path

from phenotyping_agent.state import LedgerEntry


class LedgerStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "ledger.json"

    def append(self, entry: LedgerEntry) -> None:
        entries = self.load()
        entries.append(entry)
        self.path.write_text(
            json.dumps([item.model_dump(mode="json") for item in entries], indent=2),
            encoding="utf-8",
        )

    def load(self) -> list[LedgerEntry]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [LedgerEntry.model_validate(item) for item in payload]


def render_ledger_markdown(entries: list[LedgerEntry]) -> str:
    if not entries:
        return "No iterations recorded."
    lines = ["| Iteration | Action | Cohort ID | Expectations |", "|---|---|---:|---:|"]
    for entry in entries:
        lines.append(
            f"| {entry.iteration} | {entry.next_action} | {entry.cohort_id or ''} | {len(entry.expectations)} |"
        )
    return "\n".join(lines)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

