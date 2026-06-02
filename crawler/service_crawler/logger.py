"""
logger.py — Thin wrapper around structured JSON logging for service_crawler.

Reuses the same JSON-line format as degradation_crawler so log lines can be
shipped to Loki / parsed by the same dashboards.

Environment variables:
  MACHINE_ID — node label (default: hostname)
  LOKI_URL   — Loki push endpoint (optional)
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone

import requests as _requests

MACHINE_ID: str = os.environ.get("MACHINE_ID", socket.gethostname())
LOKI_URL:   str = os.environ.get("LOKI_URL", "")
RUN_ID:     str = str(uuid.uuid4())[:8]

try:
    import subprocess as _sp
    CODE_SHA: str = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=_sp.DEVNULL,
    ).decode().strip()
except Exception:
    CODE_SHA = "unknown"


def log(level: str, event: str, **fields) -> None:
    entry = {
        "ts":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level":   level.upper(),
        "event":   event,
        "machine": MACHINE_ID,
        "run_id":  RUN_ID,
        "sha":     CODE_SHA,
        **fields,
    }
    print(json.dumps(entry), flush=True)
    _push_loki(entry)


def _push_loki(entry: dict) -> None:
    if not LOKI_URL:
        return
    payload = {
        "streams": [{
            "stream": {
                "job":     "service_crawler",
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
        pass

