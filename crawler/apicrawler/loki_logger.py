"""
loki_logger.py — Grafana Loki logging for the API crawler.

Reads the same env vars used by the main API telemetry module:
  GRAFANA_LOKI_INSTANCE_ID  — Loki instance / tenant ID
  GRAFANA_TOKEN             — Access Policy token (logs:write)
  GRAFANA_LOKI_URL          — default: https://logs-prod-025.grafana.net/loki/api/v1/push

Usage in crawl.py:
    from loki_logger import get_loki_logger
    log = get_loki_logger("apicrawler", farm="kelmarsh", pattern="farm_stopped", pi="pi1")
    log.info("hello grafana")

If credentials are absent the logger falls back to stdout-only (no crash).
"""

import base64
import json
import logging
import os
import threading

import requests as _requests

# ── Credentials (same vars as app/telemetry.py) ───────────────────────────────
_LOKI_INSTANCE_ID = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
_TOKEN            = os.environ.get("GRAFANA_TOKEN", "")
_LOKI_URL         = os.environ.get("GRAFANA_LOKI_URL",
                        "https://logs-prod-025.grafana.net/loki/api/v1/push")
_ENV              = os.environ.get("ENVIRONMENT", "production")

_loki_creds   = base64.b64encode(f"{_LOKI_INSTANCE_ID}:{_TOKEN}".encode()).decode()
_LOKI_ENABLED = bool(_LOKI_INSTANCE_ID and _TOKEN)


class _LokiHandler(logging.Handler):
    """Non-blocking Loki HTTP push — fires a daemon thread per log record."""

    def __init__(self, static_labels: dict):
        super().__init__()
        self._static_labels = static_labels
        self._headers = {
            "Authorization": f"Basic {_loki_creds}",
            "Content-Type":  "application/json",
        }

    def emit(self, record: logging.LogRecord):
        if not _LOKI_ENABLED:
            return
        try:
            msg = self.format(record)
            ts  = str(int(record.created * 1e9))
            # Also pick up any loki_* extras attached via extra={} at call site
            extra = {
                k: str(v)
                for k, v in record.__dict__.items()
                if k.startswith("loki_")
            }
            stream = {
                "app":   "apicrawler",
                "level": record.levelname.lower(),
                "env":   _ENV,
                **self._static_labels,
                **extra,
            }
            payload = {
                "streams": [{
                    "stream": stream,
                    "values": [[ts, msg]],
                }]
            }
            threading.Thread(
                target=self._push, args=(payload,), daemon=True
            ).start()
        except Exception:
            self.handleError(record)

    def _push(self, payload: dict):
        try:
            _requests.post(
                _LOKI_URL,
                data=json.dumps(payload),
                headers=self._headers,
                timeout=5,
            )
        except Exception:
            pass  # never crash the crawler because Loki is unreachable


def get_loki_logger(
    name: str = "apicrawler",
    *,
    farm:    str = "",
    pattern: str = "",
    pi:      str = "",
) -> logging.Logger:
    """
    Return a logger that writes to stdout AND (when credentials present) to Loki.

    Stream labels sent to Loki:
      app=apicrawler  level=info|warning|error  env=production
      farm=<farm>     pattern=<pattern>          pi=<pi>
    """
    logger = logging.getLogger(name)
    # Avoid duplicate handlers if called multiple times with same name
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # ── stdout ────────────────────────────────────────────────────────────────
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(sh)

    # ── Loki ──────────────────────────────────────────────────────────────────
    static_labels = {}
    if farm:    static_labels["farm"]    = farm
    if pattern: static_labels["pattern"] = pattern
    if pi:      static_labels["pi"]      = pi

    lh = _LokiHandler(static_labels)
    lh.setFormatter(logging.Formatter("%(message)s"))
    lh.setLevel(logging.INFO)   # don't push DEBUG noise to Loki
    logger.addHandler(lh)

    if _LOKI_ENABLED:
        logger.info(
            f"Loki logging enabled → {_LOKI_URL} "
            f"(labels: {static_labels})",
        )
    else:
        logger.warning(
            "GRAFANA_LOKI_INSTANCE_ID / GRAFANA_TOKEN not set — "
            "Loki logging disabled (stdout only)."
        )

    return logger

