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
        """Insert the entry, replacing any existing entry for the same iteration."""
        entries = [item for item in self.load() if item.iteration != entry.iteration]
        entries.append(entry)
        entries.sort(key=lambda item: item.iteration)
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
    lines = [
        "| Iteration | Change | Cohort ID | Final count | Held | Violated | Uninformative | PPV | Sens | Next |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for entry in entries:
        held = sum(1 for v in entry.verdicts if v.verdict == "held")
        violated = sum(1 for v in entry.verdicts if v.verdict == "violated")
        uninformative = sum(1 for v in entry.verdicts if v.verdict == "uninformative")
        final = ""
        for row in reversed(entry.counts.rows):
            if row.incremental_persons is not None:
                final = str(row.incremental_persons)
                break
        ppv = f"{entry.keeper.ppv:.3f}" if entry.keeper else ""
        sens = f"{entry.keeper.sensitivity:.3f}" if entry.keeper else ""
        change = (entry.change_from_previous or "").replace("|", "/")[:80]
        lines.append(
            f"| {entry.iteration} | {change} | {entry.cohort_id or ''} | {final} | {held} | "
            f"{violated} | {uninformative} | {ppv} | {sens} | {entry.next_action} |"
        )
    return "\n".join(lines)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

