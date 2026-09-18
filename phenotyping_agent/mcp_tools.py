from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from contextlib import AsyncExitStack, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from langchain_mcp_adapters.client import MultiServerMCPClient

from phenotyping_agent.config import AppConfig
from phenotyping_agent.state import Expectation

EXPECTED_TOOLS = {
    "listConceptSets",
    "getConceptSetsCapr",
    "getCohortCount",
    "getDatabaseDescription",
    "countConceptSetPersonOverlap",
    "describeMeasurementValues",
    "computeIncidenceRate",
    "validateCapr",
    "convertCaprToJson",
    "generateCohort",
    "evaluateCohort",
    "samplePatientProfile",
}

DIAGNOSTIC_TOOLS = {
    "getCohortCount": "cohortCount",
    "computeIncidenceRate": "incidenceRate",
    "countConceptSetPersonOverlap": "conceptSetOverlap",
    "describeMeasurementValues": "measurementValues",
    "evaluateCohort": "keeperMetrics",
}

# Per-tool read timeouts. Without these an unattended run hangs forever on a wedged server
# instead of failing with something a human can read. The R server is single-threaded, so these
# are deliberately generous: a long Databricks query blocks the whole run.
DEFAULT_TOOL_TIMEOUT_SECONDS = 600
TOOL_TIMEOUT_SECONDS = {
    "generateCohort": 2400,
    "evaluateCohort": 2400,
    "samplePatientProfile": 1200,
    "countConceptSetPersonOverlap": 1200,
    "describeMeasurementValues": 1200,
    "computeIncidenceRate": 1200,
    "getCohortCount": 900,
}

# Retrying a cohort generation or an evaluation could double a very expensive operation, or
# silently spend the KEEPER budget twice. Everything else is a read and is safe to retry once.
NON_RETRYABLE_TOOLS = {"generateCohort", "evaluateCohort"}


class McpToolError(RuntimeError):
    """The server executed the tool and reported a failure. Retrying will not help."""


@dataclass(slots=True)
class ToolBudget:
    evaluate_calls_used: int = 0


class FakeToolClient:
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def list_tools(self) -> set[str]:
        return set(EXPECTED_TOOLS)

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        fixture = self.fixture_dir / f"{name}.json"
        if fixture.exists():
            return json.loads(fixture.read_text(encoding="utf-8"))
        defaults: dict[str, Any] = {
            "listConceptSets": "| conceptsetName | withDescendants | personCount |\n|---|---|---|\n| Acute liver failure | Y | 100 |",
            "getDatabaseDescription": "Claims and linked labs data.",
            "getConceptSetsCapr": [
                {
                    "capr": "cs(concept(12345), name = \"Acute liver failure\")",
                    "conditionPersons": 100,
                }
            ],
            "validateCapr": "Valid",
            "generateCohort": 101,
            "getCohortCount": [
                {"ruleSequence": 0, "name": "Initial event", "incrementalPersons": 75}
            ],
            "computeIncidenceRate": [
                {
                    "stratum": "Overall",
                    "stratumName": "Overall",
                    "persons": 1000000,
                    "events": 75,
                    "personYears": 900000.0,
                    "incidenceRatePer1000PersonYears": 0.083,
                }
            ],
            "countConceptSetPersonOverlap": (
                "| conceptSetName | windowName | startDay | endDay | conditionPersons | "
                "conditionCohortPersons | overallPersons | overallCohortPersons |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| Acute liver failure | Index date | 0 | 0 | 100 | 75 | 100 | 75 |"
            ),
            "describeMeasurementValues": [{"conceptSetName": "INR", "unitConceptName": "ratio"}],
            "evaluateCohort": [
                {
                    "sensitivity": 0.82,
                    "specificity": 0.99,
                    "ppv": 0.84,
                    "tp": 84,
                    "fp": 16,
                    "tn": 990,
                    "fn": 18,
                }
            ],
            "samplePatientProfile": {"type": "FP", "patientProfile": "example", "rationale": "example"},
            "convertCaprToJson": "{\"ConceptSets\":[]}",
        }
        return defaults.get(name)


def load_mcp_connections(mcp_config_path: Path, project_root: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(mcp_config_path.read_text(encoding="utf-8"))
    servers = raw.get("servers", {})
    connections: dict[str, dict[str, Any]] = {}
    for name, spec in servers.items():
        if "command" in spec:
            connections[name] = {
                "transport": "stdio",
                "command": spec["command"],
                "args": list(spec.get("args", [])),
                "cwd": str(project_root),
            }
            continue

        if "url" in spec:
            transport = str(spec.get("transport") or spec.get("type") or "http")
            connections[name] = {
                "transport": transport,
                "url": spec["url"],
            }
            continue

        raise RuntimeError(f"Unsupported MCP server config for '{name}': {spec}")
    return connections


class LiveToolClient:
    def __init__(self, mcp_config_path: Path, project_root: Path) -> None:
        self.connections = load_mcp_connections(mcp_config_path, project_root)
        self.client = MultiServerMCPClient(self.connections, tool_name_prefix=False)
        self.tools_by_name: dict[str, str] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}
        self._initialize_client_sync()

    def _get_event_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create a persistent event loop for the MCP client connection."""
        if self._event_loop is None or self._event_loop.is_closed():
            try:
                self._event_loop = asyncio.get_event_loop()
                if self._event_loop.is_closed():
                    self._event_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(self._event_loop)
            except RuntimeError:
                self._event_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._event_loop)
        return self._event_loop

    async def _initialize_client_async(self) -> None:
        """Initialize MCP sessions and index tools while keeping sessions open."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for server_name in self.connections.keys():
            session = await self._exit_stack.enter_async_context(self.client.session(server_name))
            self._sessions[server_name] = session
            cursor: str | None = None
            while True:
                listed = await session.list_tools(cursor=cursor)
                for tool in listed.tools:
                    if tool.name in self.tools_by_name:
                        raise RuntimeError(f"Duplicate MCP tool name detected: {tool.name}")
                    self.tools_by_name[tool.name] = server_name
                cursor = listed.nextCursor
                if not cursor:
                    break

    def _initialize_client_sync(self) -> None:
        """Initialize client using the persistent event loop."""
        loop = self._get_event_loop()
        loop.run_until_complete(self._initialize_client_async())

    def list_tools(self) -> set[str]:
        return set(self.tools_by_name.keys())

    @staticmethod
    def _normalize_text_blocks(payload: Any) -> Any:
        if not isinstance(payload, list):
            return payload
        texts: list[str] = []
        for item in payload:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and "text" in item:
                texts.append(str(item["text"]))
            elif hasattr(item, "text"):
                texts.append(str(getattr(item, "text")))
        if not texts:
            return payload
        merged = "\n".join(texts)
        try:
            return json.loads(merged)
        except json.JSONDecodeError:
            return merged

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        server_name = self.tools_by_name.get(name)
        if server_name is None:
            raise RuntimeError(f"Unknown MCP tool '{name}'")
        session = self._sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"No active MCP session for server '{server_name}'")
        loop = self._get_event_loop()
        timeout = timedelta(
            seconds=TOOL_TIMEOUT_SECONDS.get(name, DEFAULT_TOOL_TIMEOUT_SECONDS)
        )
        result = loop.run_until_complete(
            session.call_tool(name=name, arguments=args, read_timeout_seconds=timeout)
        )
        if getattr(result, "isError", False):
            content = self._normalize_text_blocks(getattr(result, "content", None))
            raise McpToolError(f"MCP tool '{name}' failed: {content}")
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        return self._normalize_text_blocks(getattr(result, "content", result))

    async def _cleanup_async(self) -> None:
        """Clean up all sessions."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.__aexit__(None, None, None)
            except Exception:
                # Some transports can only be exited from their original task.
                # Keep shutdown best-effort; process exit will clean up subprocesses.
                pass
            self._exit_stack = None

    def close(self) -> None:
        """Close all active MCP sessions explicitly."""
        loop = self._event_loop
        if loop is None or loop.is_closed() or self._exit_stack is None:
            return
        try:
            loop.run_until_complete(self._cleanup_async())
        except Exception:
            self._exit_stack = None

    def __del__(self) -> None:
        """Clean up sessions when the client is destroyed."""
        if sys.is_finalizing():
            return
        loop = self._event_loop
        if loop is not None and not loop.is_closed() and self._exit_stack is not None:
            try:
                self.close()
            except Exception:
                pass


class ToolFacade:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.log_path = config.runs_dir / "tool_calls.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget = ToolBudget()
        self.pending_expectations: list[Expectation] = []
        self.consumed_expectations: list[Expectation] = []
        self.call_counts: Counter[str] = Counter()
        self.incidence_cohorts: set[int] = set()
        self.overlap_cohorts: set[int] = set()
        self._allowed: set[str] | None = None
        self.client = (
            FakeToolClient(config.project_root / "tests" / "fixtures")
            if config.dry_run
            else LiveToolClient(config.mcp_config_path, config.project_root)
        )
        self._assert_toolset()

    def close(self) -> None:
        closer = getattr(self.client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def _assert_toolset(self) -> None:
        found = self.client.list_tools()
        missing = EXPECTED_TOOLS - found
        if missing:
            extra = sorted(found - EXPECTED_TOOLS)
            raise RuntimeError(f"Tool mismatch. Missing={sorted(missing)} Extra={extra}")

    # ------------------------------------------------------------ allow-lists
    @contextmanager
    def restrict_to(self, allowed: set[str]) -> Iterator["ToolFacade"]:
        """Limit which tools may be called inside the block (per-node allow-lists)."""
        previous = self._allowed
        self._allowed = set(allowed)
        try:
            yield self
        finally:
            self._allowed = previous

    # ---------------------------------------------------------- expectations
    def record_expectation(self, expectation: Expectation) -> None:
        key = (expectation.diagnostic, expectation.target, expectation.claim)
        existing = {(e.diagnostic, e.target, e.claim) for e in self.pending_expectations}
        if key in existing:
            return
        self.pending_expectations.append(expectation)

    def has_pending(self, diagnostic: str, target: str = "overall") -> bool:
        return any(
            e.diagnostic == diagnostic and e.target == target for e in self.pending_expectations
        )

    def reset_expectations(self) -> None:
        """Drop expectations left over from a previous iteration."""
        self.pending_expectations = []
        self.consumed_expectations = []

    def _consume_expectation(self, diagnostic: str, target: str) -> list[Expectation]:
        matched = [e for e in self.pending_expectations if e.diagnostic == diagnostic and e.target == target]
        if not matched:
            raise RuntimeError(
                f"Expectation gating failed for diagnostic='{diagnostic}', target='{target}'. "
                "Call record_expectation first."
            )
        self.pending_expectations = [
            e for e in self.pending_expectations if not (e.diagnostic == diagnostic and e.target == target)
        ]
        self.consumed_expectations.extend(matched)
        return matched

    def _invoke(self, name: str, args: dict[str, Any]) -> Any:
        """Call the tool, retrying once on a transport failure.

        A `McpToolError` means the server ran the tool and it failed, so a retry only wastes
        time. Anything else is a transport or timeout problem, which is worth one retry - except
        for tools that must never run twice.
        """
        try:
            return self.client.call_tool(name, args)
        except McpToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            if name in NON_RETRYABLE_TOOLS:
                raise
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"tool": name, "args": args, "retry_after_error": str(exc)}) + "\n"
                )
            return self.client.call_tool(name, args)

    def _call(self, name: str, args: dict[str, Any], target: str = "overall") -> Any:
        if self._allowed is not None and name not in self._allowed:
            raise RuntimeError(
                f"Tool '{name}' is not available to the current node. "
                f"Allowed: {sorted(self._allowed)}"
            )
        if name in DIAGNOSTIC_TOOLS:
            self._consume_expectation(DIAGNOSTIC_TOOLS[name], target)
        if name == "evaluateCohort" and self.budget.evaluate_calls_used >= self.config.budgets.evaluate_calls:
            raise RuntimeError("evaluateCohort budget exhausted")

        result = self._invoke(name, args)

        # Counted only after the call succeeds: a phenotype with no KEEPER reference cohort fails
        # immediately, and burning a third of a three-call budget on that would be wrong.
        if name == "evaluateCohort":
            self.budget.evaluate_calls_used += 1
        self.call_counts[name] += 1
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"tool": name, "args": args, "result": result}) + "\n")
        return result

    def list_concept_sets(self, phenotype: str) -> Any:
        return self._call("listConceptSets", {"phenotype": phenotype})

    def get_database_description(self, database_name: str) -> Any:
        return self._call("getDatabaseDescription", {"databaseName": database_name})

    def get_concept_sets_capr(self, phenotype: str, concept_set_names: list[str], detail: str = "code_and_counts") -> Any:
        return self._call(
            "getConceptSetsCapr",
            {"phenotype": phenotype, "conceptSetNames": concept_set_names, "detail": detail},
        )

    def fetch_concept_set_snippets(
        self, phenotype: str, concept_set_names: list[str]
    ) -> tuple[dict[str, str], list[str]]:
        """Return ``{name: verbatim cs(...) code}`` plus the names that could not be resolved.

        Snippets are stored verbatim so that the static concept-ID check in
        ``capr_checks.validate_capr_static`` has an authoritative allow-list.

        `getConceptSetsCapr` returns no name column: rows come back in the order requested. That
        is only safe when every requested name resolved. If any name is unknown (a typo or an
        invented set) the rows shift and each snippet would be filed under the wrong name - a
        silent corruption that would put the wrong concept IDs in the cohort. So when the row
        count does not match, fall back to resolving one name at a time, where the mapping is
        unambiguous.
        """
        if not concept_set_names:
            return {}, []

        rows = self._snippet_rows(self.get_concept_sets_capr(phenotype, concept_set_names))
        if len(rows) == len(concept_set_names):
            registry = dict(zip(concept_set_names, rows))
            return registry, []

        registry = {}
        for name in concept_set_names:
            single = self._snippet_rows(self.get_concept_sets_capr(phenotype, [name]))
            if len(single) == 1:
                registry[name] = single[0]
        gaps = [name for name in concept_set_names if name not in registry]
        return registry, gaps

    @staticmethod
    def _snippet_rows(payload: Any) -> list[str]:
        """Extract the verbatim `capr` snippets from a `getConceptSetsCapr` payload."""
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        snippets: list[str] = []
        for row in payload:
            if isinstance(row, dict):
                snippet = str(row.get("capr", "")).strip()
            elif isinstance(row, str):
                snippet = row.strip()
            else:
                continue
            if snippet:
                snippets.append(snippet)
        return snippets

    def validate_capr(self, capr_code: str) -> Any:
        return self._call("validateCapr", {"caprCode": capr_code})

    def generate_cohort(self, capr_code: str) -> int:
        return int(self._call("generateCohort", {"caprCode": capr_code}))

    def get_cohort_count(self, cohort_id: int) -> Any:
        return self._call("getCohortCount", {"cohortId": cohort_id}, target="overall")

    def compute_incidence_rate(self, cohort_id: int) -> Any:
        result = self._call("computeIncidenceRate", {"cohortId": cohort_id}, target="overall")
        self.incidence_cohorts.add(int(cohort_id))
        return result

    def count_concept_set_overlap(self, capr_code: list[str], cohort_id: int) -> Any:
        result = self._call(
            "countConceptSetPersonOverlap",
            {"caprCode": capr_code, "cohortId": cohort_id},
            target="overall",
        )
        self.overlap_cohorts.add(int(cohort_id))
        return result

    def describe_measurements(self, capr_code: list[str], target: str) -> Any:
        return self._call("describeMeasurementValues", {"caprCode": capr_code}, target=target)

    def evaluate_cohort(self, cohort_id: int, phenotype: str) -> Any:
        return self._call(
            "evaluateCohort",
            {"cohortId": cohort_id, "phenotype": phenotype},
            target="overall",
        )

    def sample_patient_profile(self, cohort_id: int, phenotype: str, ptype: str) -> Any:
        return self._call(
            "samplePatientProfile",
            {"cohortId": cohort_id, "phenotype": phenotype, "type": ptype},
        )

    def convert_capr_to_json(self, capr_code: str) -> str:
        result = self._call("convertCaprToJson", {"caprCode": capr_code})
        return result if isinstance(result, str) else json.dumps(result)


