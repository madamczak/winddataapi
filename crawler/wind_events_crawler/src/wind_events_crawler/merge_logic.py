from __future__ import annotations

from datetime import datetime, timezone

from .models import Finding


def merge_findings(existing: list[Finding], incoming: list[Finding]) -> list[Finding]:
    merged: list[Finding] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for finding in [*existing, *incoming]:
        key = (
            finding.scenario,
            finding.farm,
            finding.turbine,
            _normalize_utc_identity_value(finding.evaluated_window_start_utc),
            _normalize_utc_identity_value(finding.evaluated_window_end_utc),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(finding)
    return merged


def _normalize_utc_identity_value(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    normalized = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")
