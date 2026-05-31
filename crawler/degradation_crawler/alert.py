"""
alert.py — Phase 5: Write output files and push events to Grafana Loki.

Responsibilities:
  1. Append drift alert dicts to degradation_alerts.jsonl (one line per alert).
  2. Append AssessmentRecord dicts to healthy_records.jsonl or degrading_records.jsonl.
  3. Push each event to Loki (best-effort — failures never crash the crawler).

All three output files live under crawler/degradation_crawler/results/.
They are append-only JSONL files; the frontend export script cherry-picks the
latest record per turbine/column before serving the UI.
"""

from __future__ import annotations

import json
from pathlib import Path

from .classify import AssessmentRecord
from .config import ALERTS_JSONL, DEGRADING_JSONL, HEALTHY_JSONL, RESULTS_DIR
from .machine_logger import log


# ---------------------------------------------------------------------------
# Drift alert writer
# ---------------------------------------------------------------------------

def write_alert(alert: dict, path: Path = ALERTS_JSONL) -> None:
    """
    Append a single drift alert dict to the alerts JSONL file.

    alert keys (from drift_detect.detect_drift):
        farm, turbine, col, severity, direction, date, hour,
        mean_delta, window_n, slope_per_month
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(alert) + "\n")

    log(
        "INFO" if alert.get("severity") == "WATCH" else "WARN",
        "drift_alert",
        farm=alert.get("farm", ""),
        turbine=alert.get("turbine", ""),
        col=alert.get("col", ""),
        severity=alert.get("severity", ""),
        mean_delta=alert.get("mean_delta"),
        date=alert.get("date", ""),
    )


def write_alerts(alerts: list[dict], path: Path = ALERTS_JSONL) -> int:
    """Write a batch of drift alerts. Returns the number written."""
    for a in alerts:
        write_alert(a, path)
    return len(alerts)


# ---------------------------------------------------------------------------
# Assessment record writer
# ---------------------------------------------------------------------------

def write_assessment(record: AssessmentRecord) -> None:
    """
    Append an AssessmentRecord to either healthy_records.jsonl or
    degrading_records.jsonl depending on the record's bin.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if record.bin == "HEALTHY":
        out_path = HEALTHY_JSONL
        log_level = "INFO"
        log_event  = "assessment_healthy"
    else:
        out_path = DEGRADING_JSONL
        log_level = "WARN" if record.severity in ("WARNING", "CRITICAL") else "INFO"
        log_event  = "assessment_degrading"

    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict()) + "\n")

    log(
        log_level, log_event,
        farm=record.farm,
        turbine=record.turbine,
        col=record.col,
        severity=record.severity,
        mean_delta=record.mean_delta,
        score=record.evidence_score,
        n_obs=record.n_obs,
    )


def write_assessments(records: list[AssessmentRecord]) -> tuple[int, int]:
    """
    Write a batch of AssessmentRecords.

    Returns (healthy_count, degrading_count).
    """
    healthy = degrading = 0
    for rec in records:
        write_assessment(rec)
        if rec.bin == "HEALTHY":
            healthy += 1
        else:
            degrading += 1
    return healthy, degrading

