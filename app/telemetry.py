"""
API telemetry:
  - Structured logging  → stdout + Grafana Loki (async HTTP push)
  - Metrics             → Grafana Mimir via OTLP

Required env vars (optional — telemetry is silently disabled when missing):
  GRAFANA_LOKI_INSTANCE_ID      e.g. 1380423
  GRAFANA_METRICS_INSTANCE_ID   e.g. 1422629
  GRAFANA_TOKEN                 Access Policy token (logs:write + metrics:write)
  GRAFANA_LOKI_URL              default: https://logs-prod-025.grafana.net/loki/api/v1/push
  GRAFANA_OTLP_ENDPOINT         default: https://otlp-gateway-prod-eu-north-0.grafana.net/otlp
  ENVIRONMENT                   default: production
"""
import base64
import json
import logging
import os
import threading

import requests as _requests
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

# ── Credentials ───────────────────────────────────────────────────────────────
_LOKI_INSTANCE_ID    = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
_METRICS_INSTANCE_ID = os.environ.get("GRAFANA_METRICS_INSTANCE_ID", "")
_TOKEN               = os.environ.get("GRAFANA_TOKEN", "")
_LOKI_URL            = os.environ.get("GRAFANA_LOKI_URL",
                           "https://logs-prod-025.grafana.net/loki/api/v1/push")
_OTLP_ENDPOINT       = os.environ.get("GRAFANA_OTLP_ENDPOINT",
                           "https://otlp-gateway-prod-eu-north-0.grafana.net/otlp")
_ENV                 = os.environ.get("ENVIRONMENT", "production")

_loki_creds    = base64.b64encode(f"{_LOKI_INSTANCE_ID}:{_TOKEN}".encode()).decode()
_metrics_creds = base64.b64encode(f"{_METRICS_INSTANCE_ID}:{_TOKEN}".encode()).decode()

_LOKI_ENABLED    = bool(_LOKI_INSTANCE_ID and _TOKEN)
_METRICS_ENABLED = bool(_METRICS_INSTANCE_ID and _TOKEN)


# ── Loki HTTP handler ─────────────────────────────────────────────────────────
class _LokiHandler(logging.Handler):
    """Non-blocking Loki push — fires a daemon thread per log record."""

    _headers = {
        "Authorization": f"Basic {_loki_creds}",
        "Content-Type":  "application/json",
    }

    def emit(self, record: logging.LogRecord):
        if not _LOKI_ENABLED:
            return
        try:
            msg  = self.format(record)
            ts   = str(int(record.created * 1e9))
            # Extra fields attached via logger.info(..., extra={...})
            extra_labels = {
                k: str(v)
                for k, v in record.__dict__.items()
                if k.startswith("loki_")
            }
            payload = {
                "streams": [{
                    "stream": {
                        "app":   "winddataAPI",
                        "level": record.levelname.lower(),
                        "env":   _ENV,
                        **extra_labels,
                    },
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
            pass  # never crash the API because Loki is unreachable


# ── Public logger factory ─────────────────────────────────────────────────────
def get_logger(name: str = "winddataAPI") -> logging.Logger:
    """Return a logger that writes to stdout and (if configured) to Loki."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    # stdout — always on
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
    ))
    logger.addHandler(sh)

    # Loki — only when credentials present
    lh = _LokiHandler()
    lh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(lh)

    return logger


# ── OTLP metrics setup ────────────────────────────────────────────────────────
_resource = Resource.create({
    "service.name":           "winddataAPI",
    "service.version":        "1.0.0",
    "deployment.environment": _ENV,
})

if _METRICS_ENABLED:
    _exporter = OTLPMetricExporter(
        endpoint=f"{_OTLP_ENDPOINT}/v1/metrics",
        headers={"Authorization": f"Basic {_metrics_creds}"},
    )
    _reader = PeriodicExportingMetricReader(
        _exporter, export_interval_millis=30_000
    )
    _provider = MeterProvider(resource=_resource, metric_readers=[_reader])
else:
    # No-op provider so the rest of the code still works without credentials
    _provider = MeterProvider(resource=_resource)

metrics.set_meter_provider(_provider)
_meter = metrics.get_meter("winddataAPI.api")

# ── Instruments ───────────────────────────────────────────────────────────────
request_counter = _meter.create_counter(
    "api_requests_total",
    description="Total HTTP requests handled by the API",
    unit="1",
)
error_counter = _meter.create_counter(
    "api_errors_total",
    description="Total 4xx / 5xx responses",
    unit="1",
)
request_duration = _meter.create_histogram(
    "api_request_duration_seconds",
    description="End-to-end request duration in seconds",
    unit="s",
)
rows_returned = _meter.create_histogram(
    "api_rows_returned",
    description="Rows returned by turbine query endpoints",
    unit="1",
)

