"""
machine_logger.py — Structured JSON logging with machine identity.

Every log line carries:
  ts        — UTC ISO timestamp
  level     — INFO / WARN / ERROR / DEBUG
  event     — snake_case event name (e.g. "heartbeat_start")
  machine   — node name from MACHINE_ID env var (or OS hostname)
  run_id    — 8-char UUID prefix, unique per scheduler invocation
  sha       — short git commit hash of the running code

Log lines are printed to stdout (captured by systemd → journal / log file)
and pushed to Grafana Loki (best-effort; Loki failures never crash the crawler).

Environment variables:
  MACHINE_ID  — human-readable node name, e.g. "pi-1" (default: hostname)
  LOKI_URL    — Loki push endpoint, e.g. "http://grafana-host:3100"
                Leave empty to disable Loki push.

Loki label strategy (keep cardinality low — docs §14.3):
  job     = "windcrawler"   (constant — top-level namespace)
  machine = MACHINE_ID      (one stream per node)
  level   = INFO/WARN/ERROR  (3 values)

All other fields (turbine, farm, run_id, sha, …) live inside the JSON body
and are parsed at query time with | json in LogQL.

Standard log events (docs §14.4):
  heartbeat_start   — beginning of a scheduler invocation
  heartbeat_end     — end of a scheduler invocation (includes totals)
  baseline_start    — baseline build started for a turbine
  baseline_built    — baseline build completed
  scan_start        — scan phase started
  scan_done         — scan phase finished
  drift_alert       — a drift threshold was crossed
  assessment_healthy   — HEALTHY record written
  assessment_degrading — DEGRADING record written
  turbine_done      — one turbine fully processed in a run
  turbine_failed    — exception during turbine processing
  api_retry         — retrying a failed API request
  code_updated      — git pull applied a new version
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

import requests as _requests

# ---------------------------------------------------------------------------
# Module-level identity — computed once at import time
# ---------------------------------------------------------------------------
MACHINE_ID: str = os.environ.get("MACHINE_ID", socket.gethostname())
LOKI_URL:   str = os.environ.get("LOKI_URL", "")
RUN_ID:     str = str(uuid.uuid4())[:8]   # unique per process invocation

try:
    import subprocess as _sp
    CODE_SHA: str = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=_sp.DEVNULL,
    ).decode().strip()
except Exception:
    CODE_SHA = "unknown"


# ---------------------------------------------------------------------------
# Public logging function
# ---------------------------------------------------------------------------

def log(level: str, event: str, **fields) -> None:
    """
    Emit one structured JSON log line and push to Loki (best-effort).

    Parameters
    ----------
    level : str
        Severity: "INFO", "WARN", "ERROR", or "DEBUG".
    event : str
        Snake-case event name, e.g. "heartbeat_start".
    **fields : Any
        Arbitrary key/value pairs injected into the JSON body.
        Common: farm=, turbine=, rows=, error=, duration_s=
    """
    entry = {
        "ts":      _now_utc(),
        "level":   level.upper(),
        "event":   event,
        "machine": MACHINE_ID,
        "run_id":  RUN_ID,
        "sha":     CODE_SHA,
        **fields,
    }
    print(json.dumps(entry), flush=True)   # systemd captures stdout → journal
    _push_loki(entry)


# ---------------------------------------------------------------------------
# Loki push (fire-and-forget)
# ---------------------------------------------------------------------------

def _push_loki(entry: dict) -> None:
    """Push a log entry to Loki. Silently swallowed on any failure."""
    if not LOKI_URL:
        return

    payload = {
        "streams": [{
            "stream": {
                "job":     "windcrawler",
                "machine": MACHINE_ID,
                "level":   entry["level"],
            },
            "values": [
                [str(int(time.time() * 1_000_000_000)), json.dumps(entry)]
            ],
        }]
    }
    try:
        _requests.post(
            f"{LOKI_URL}/loki/api/v1/push",
            json=payload,
            timeout=4,
        )
    except Exception:
        pass   # monitoring must NEVER crash the crawler


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

