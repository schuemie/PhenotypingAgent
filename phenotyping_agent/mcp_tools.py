from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
            "countConceptSetPersonOverlap": [{"conceptSetName": "Acute liver failure"}],
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
        self.tools_by_name = self._load_tools()

    def _load_tools(self) -> dict[str, Any]:
        tools = asyncio.run(self.client.get_tools())
        mapped: dict[str, Any] = {}
        for tool in tools:
            if tool.name in mapped:
                raise RuntimeError(f"Duplicate MCP tool name detected: {tool.name}")
            mapped[tool.name] = tool
        return mapped

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
        tool = self.tools_by_name.get(name)
        if tool is None:
            raise RuntimeError(f"Unknown MCP tool '{name}'")
        result = asyncio.run(tool.ainvoke(args))
        if hasattr(result, "content"):
            content = result.content
            return self._normalize_text_blocks(content)
        return self._normalize_text_blocks(result)


class ToolFacade:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.log_path = config.runs_dir / "tool_calls.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget = ToolBudget()
        self.pending_expectations: list[Expectation] = []
        self.consumed_expectations: list[Expectation] = []
        self.client = (
            FakeToolClient(config.project_root / "tests" / "fixtures")
            if config.dry_run
            else LiveToolClient(config.mcp_config_path, config.project_root)
        )
        self._assert_toolset()

    def _assert_toolset(self) -> None:
        found = self.client.list_tools()
        missing = EXPECTED_TOOLS - found
        if missing:
            extra = sorted(found - EXPECTED_TOOLS)
            raise RuntimeError(f"Tool mismatch. Missing={sorted(missing)} Extra={extra}")

    def record_expectation(self, expectation: Expectation) -> None:
        self.pending_expectations.append(expectation)

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

    def _call(self, name: str, args: dict[str, Any], target: str = "overall") -> Any:
        if name in DIAGNOSTIC_TOOLS:
            self._consume_expectation(DIAGNOSTIC_TOOLS[name], target)
        if name == "evaluateCohort":
            if self.budget.evaluate_calls_used >= self.config.budgets.evaluate_calls:
                raise RuntimeError("evaluateCohort budget exhausted")
            self.budget.evaluate_calls_used += 1
        result = self.client.call_tool(name, args)
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

    def validate_capr(self, capr_code: str) -> Any:
        return self._call("validateCapr", {"caprCode": capr_code})

    def generate_cohort(self, capr_code: str) -> int:
        return int(self._call("generateCohort", {"caprCode": capr_code}))

    def get_cohort_count(self, cohort_id: int) -> Any:
        return self._call("getCohortCount", {"cohortId": cohort_id}, target="overall")

    def compute_incidence_rate(self, cohort_id: int) -> Any:
        return self._call("computeIncidenceRate", {"cohortId": cohort_id}, target="overall")

    def count_concept_set_overlap(self, capr_code: list[str], cohort_id: int) -> Any:
        return self._call(
            "countConceptSetPersonOverlap",
            {"caprCode": capr_code, "cohortId": cohort_id},
            target="overall",
        )

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


