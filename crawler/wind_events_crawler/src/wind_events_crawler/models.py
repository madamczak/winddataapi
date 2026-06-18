from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProducerContext:
    worker: str
    pi_id: str
    revision: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    scenario: str
    farm: str
    turbine: str
    evaluated_window_start_utc: str
    evaluated_window_end_utc: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ResultArtifact:
    schema_version: str
    generated_at_utc: str | None
    producer: dict[str, str | None]
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at_utc": self.generated_at_utc,
            "producer": self.producer,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True)
class PersistenceResult:
    artifact: ResultArtifact
    incoming_findings: int
    preserved_findings: int
    added_findings: int
    stored_findings: int


@dataclass(frozen=True)
class PublicationResult:
    artifact: ResultArtifact
    attempt_count: int
    conflict_retries: int
    committed: bool
    published_revision: str | None


@dataclass(frozen=True)
class ApiDataSlice:
    farm: str
    turbine: str
    evaluated_window_start_utc: str
    evaluated_window_end_utc: str
    rows: list[object] = field(default_factory=list)
    data_type: str = "data"


@dataclass(frozen=True)
class ScenarioEvaluationResult:
    scenario: str
    farm: str
    turbine: str
    evaluated_window_start_utc: str
    evaluated_window_end_utc: str
    total_rows: int
    matching_rows: int
    matches: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    pi_id: str
    scenario: str
    stage: str
    lock_path: str
    result_path: str
    revision: str | None = None


@dataclass(frozen=True)
class RunResult:
    context: RunContext
    outcome: str
    artifact: ResultArtifact | None
    recovered_stale_lock: bool = False
    scenario_result: ScenarioEvaluationResult | None = None
