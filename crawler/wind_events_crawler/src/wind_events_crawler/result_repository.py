from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import ArtifactContractError
from .merge_logic import merge_findings
from .models import Finding, PersistenceResult, ProducerContext, ResultArtifact


SCHEMA_VERSION = "0.1.0"
_ROOT_KEYS = {"schema_version", "generated_at_utc", "producer", "findings"}
_PRODUCER_KEYS = {"worker", "pi_id", "revision"}
_FINDING_KEYS = {
    "scenario",
    "farm",
    "turbine",
    "evaluated_window_start_utc",
    "evaluated_window_end_utc",
}


def _validate_object_keys(*, payload: dict[object, object], expected_keys: set[str], field_name: str) -> None:
    actual_keys = {key for key in payload if isinstance(key, str)}
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected keys: {', '.join(unexpected)}")
        raise ArtifactContractError(f"Artifact field '{field_name}' has invalid shape ({'; '.join(details)})")


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactContractError(f"Artifact field '{field_name}' must be a non-empty string")
    return value


def _require_string_or_null(value: object, *, field_name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ArtifactContractError(f"Artifact field '{field_name}' must be a string or null")
    return value


def _normalize_findings(findings_payload: object) -> list[Finding]:
    if not isinstance(findings_payload, list):
        raise ArtifactContractError("Artifact field 'findings' must be a list")

    findings: list[Finding] = []
    for index, raw_finding in enumerate(findings_payload):
        field_prefix = f"findings[{index}]"
        if not isinstance(raw_finding, dict):
            raise ArtifactContractError(f"Artifact field '{field_prefix}' must be an object")
        missing_finding_keys = sorted(_FINDING_KEYS - {key for key in raw_finding if isinstance(key, str)})
        if missing_finding_keys:
            first_missing_key = missing_finding_keys[0]
            raise ArtifactContractError(f"Artifact field '{field_prefix}.{first_missing_key}' must be a non-empty string")
        _validate_object_keys(payload=raw_finding, expected_keys=_FINDING_KEYS, field_name=field_prefix)
        findings.append(
            Finding(
                scenario=_require_non_empty_string(raw_finding.get("scenario"), field_name=f"{field_prefix}.scenario"),
                farm=_require_non_empty_string(raw_finding.get("farm"), field_name=f"{field_prefix}.farm"),
                turbine=_require_non_empty_string(raw_finding.get("turbine"), field_name=f"{field_prefix}.turbine"),
                evaluated_window_start_utc=_require_non_empty_string(
                    raw_finding.get("evaluated_window_start_utc"),
                    field_name=f"{field_prefix}.evaluated_window_start_utc",
                ),
                evaluated_window_end_utc=_require_non_empty_string(
                    raw_finding.get("evaluated_window_end_utc"),
                    field_name=f"{field_prefix}.evaluated_window_end_utc",
                ),
            )
        )
    return findings


def _normalize_artifact_payload(payload: object, *, result_path: Path) -> ResultArtifact:
    if not isinstance(payload, dict):
        raise ArtifactContractError(f"Artifact at '{result_path}' must be a JSON object")
    _validate_object_keys(payload=payload, expected_keys=_ROOT_KEYS, field_name="root")

    schema_version = payload.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ArtifactContractError(f"Unsupported schema_version '{schema_version}', expected '{SCHEMA_VERSION}'")

    generated_at_utc = _require_string_or_null(payload.get("generated_at_utc"), field_name="generated_at_utc")

    producer = payload.get("producer")
    if not isinstance(producer, dict):
        raise ArtifactContractError("Artifact field 'producer' must be an object")
    _validate_object_keys(payload=producer, expected_keys=_PRODUCER_KEYS, field_name="producer")

    worker = _require_non_empty_string(producer.get("worker"), field_name="producer.worker")
    pi_id = _require_non_empty_string(producer.get("pi_id"), field_name="producer.pi_id")
    revision = _require_string_or_null(producer.get("revision"), field_name="producer.revision")

    return ResultArtifact(
        schema_version=SCHEMA_VERSION,
        generated_at_utc=generated_at_utc,
        producer=ProducerContext(worker=worker, pi_id=pi_id, revision=revision).to_dict(),
        findings=_normalize_findings(payload.get("findings")),
    )


def build_placeholder_artifact(pi_id: str, revision: str | None = None) -> ResultArtifact:
    producer = ProducerContext(worker="wind_events_crawler", pi_id=pi_id, revision=revision)
    return ResultArtifact(
        schema_version=SCHEMA_VERSION,
        generated_at_utc=None,
        producer=producer.to_dict(),
        findings=[],
    )


def write_artifact(result_path: Path, artifact: ResultArtifact) -> None:
    normalized_artifact = _normalize_artifact_payload(artifact.to_dict(), result_path=result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_json = json.dumps(normalized_artifact.to_dict(), indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=result_path.parent,
        prefix=f"{result_path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(artifact_json)
        temp_path = Path(temp_file.name)
    os.replace(temp_path, result_path)


def load_artifact(result_path: Path) -> ResultArtifact:
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ArtifactContractError(f"Invalid text encoding in artifact at '{result_path}'") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactContractError(f"Invalid JSON artifact at '{result_path}'") from exc
    return _normalize_artifact_payload(payload, result_path=result_path)


def ensure_placeholder_artifact(result_path: Path, pi_id: str, revision: str | None = None) -> ResultArtifact:
    artifact = build_placeholder_artifact(pi_id=pi_id, revision=revision)
    if result_path.exists():
        existing_artifact = load_artifact(result_path)
        if existing_artifact.producer.get("pi_id") == pi_id and (
            revision is None or existing_artifact.producer.get("revision") == revision
        ):
            return existing_artifact

        updated_artifact = ResultArtifact(
            schema_version=existing_artifact.schema_version,
            generated_at_utc=existing_artifact.generated_at_utc,
            producer={
                "worker": existing_artifact.producer["worker"],
                "pi_id": pi_id,
                "revision": revision,
            },
            findings=existing_artifact.findings,
        )
        write_artifact(result_path, updated_artifact)
        return updated_artifact

    write_artifact(result_path, artifact)
    return artifact


def persist_findings(
    result_path: Path,
    *,
    pi_id: str,
    revision: str | None,
    findings: list[Finding],
    generated_at_utc: str | None = None,
) -> PersistenceResult:
    normalized_incoming = _normalize_incoming_findings(findings)
    if not normalized_incoming:
        artifact = ensure_placeholder_artifact(result_path, pi_id=pi_id, revision=revision)
        return PersistenceResult(
            artifact=artifact,
            incoming_findings=0,
            preserved_findings=len(artifact.findings),
            added_findings=0,
            stored_findings=len(artifact.findings),
        )

    existing_artifact = load_artifact(result_path) if result_path.exists() else build_placeholder_artifact(pi_id=pi_id, revision=revision)
    canonical_existing = merge_findings([], existing_artifact.findings)
    merged_findings = merge_findings(canonical_existing, normalized_incoming)
    artifact = ResultArtifact(
        schema_version=SCHEMA_VERSION,
        generated_at_utc=generated_at_utc or _current_utc_timestamp(),
        producer=ProducerContext(worker="wind_events_crawler", pi_id=pi_id, revision=revision).to_dict(),
        findings=merged_findings,
    )
    write_artifact(result_path, artifact)
    return PersistenceResult(
        artifact=artifact,
        incoming_findings=len(normalized_incoming),
        preserved_findings=len(canonical_existing),
        added_findings=max(len(merged_findings) - len(canonical_existing), 0),
        stored_findings=len(merged_findings),
    )


def _current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_incoming_findings(findings_payload: object) -> list[Finding]:
    if not isinstance(findings_payload, list):
        raise ArtifactContractError("Incoming findings must be provided as a list")

    normalized: list[Finding] = []
    for index, finding in enumerate(findings_payload):
        if isinstance(finding, Finding):
            normalized.append(finding)
            continue
        if isinstance(finding, dict):
            normalized.extend(_normalize_findings([finding]))
            continue
        if all(hasattr(finding, field_name) for field_name in _FINDING_KEYS):
            normalized.append(
                Finding(
                    scenario=_require_non_empty_string(getattr(finding, "scenario"), field_name=f"incoming_findings[{index}].scenario"),
                    farm=_require_non_empty_string(getattr(finding, "farm"), field_name=f"incoming_findings[{index}].farm"),
                    turbine=_require_non_empty_string(getattr(finding, "turbine"), field_name=f"incoming_findings[{index}].turbine"),
                    evaluated_window_start_utc=_require_non_empty_string(
                        getattr(finding, "evaluated_window_start_utc"),
                        field_name=f"incoming_findings[{index}].evaluated_window_start_utc",
                    ),
                    evaluated_window_end_utc=_require_non_empty_string(
                        getattr(finding, "evaluated_window_end_utc"),
                        field_name=f"incoming_findings[{index}].evaluated_window_end_utc",
                    ),
                )
            )
            continue
        raise ArtifactContractError(
            f"Incoming finding at index {index} must be a Finding or finding-shaped object"
        )
    return normalized
