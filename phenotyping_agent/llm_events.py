from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class LLMEventLogger:
    """Append-only JSONL logger for LLM request/response events."""

    def __init__(self, run_dir: Path, file_name: str = "llm_events.jsonl") -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / file_name

    def append(self, event: Mapping[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("ts", _utc_now_z())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_normalize(payload), ensure_ascii=True) + "\n")


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _normalize(model_dump(mode="json"))
    return str(value)


def extract_text(payload: Any) -> str:
    """Extract human-readable text from common LangChain payload shapes."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (list, tuple)):
        chunks: list[str] = []
        for item in payload:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], str):
                chunks.append(item[1])
            elif isinstance(item, Mapping) and "content" in item:
                chunks.append(extract_text(item["content"]))
            else:
                chunks.append(extract_text(item))
        return "\n".join(part for part in chunks if part)
    if isinstance(payload, Mapping) and "text" in payload:
        return str(payload["text"])
    content = getattr(payload, "content", None)
    if content is not None:
        return extract_text(content)
    return str(payload)


def extract_usage(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, Mapping):
        return {
            "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
            "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, Mapping):
            return {
                "input_tokens": int(token_usage.get("prompt_tokens", token_usage.get("input_tokens", 0)) or 0),
                "output_tokens": int(token_usage.get("completion_tokens", token_usage.get("output_tokens", 0)) or 0),
                "total_tokens": int(token_usage.get("total_tokens", 0) or 0),
            }

    return None

