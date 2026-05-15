"""
telemetry.py — drop-in Grafana Cloud telemetry for FastAPI.

Logs  → Loki via HTTP POST  (Basic auth: INSTANCE_ID:TOKEN)
Metrics → Mimir via OTLP HTTP (Basic auth: INSTANCE_ID:TOKEN)
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
LOKI_INSTANCE_ID    = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
METRICS_INSTANCE_ID = os.environ.get("GRAFANA_METRICS_INSTANCE_ID", "")
TOKEN               = os.environ.get("GRAFANA_TOKEN", "")

# Push endpoints — copy from your Grafana Cloud stack details page
LOKI_URL      = os.environ.get("GRAFANA_LOKI_URL",
                    "https://logs-prod-025.grafana.net/loki/api/v1/push")
OTLP_ENDPOINT = os.environ.get("GRAFANA_OTLP_ENDPOINT",
                    "https://otlp-gateway-prod-eu-north-0.grafana.net/otlp")
ENV           = os.environ.get("ENVIRONMENT", "production")

LOKI_ENABLED    = bool(LOKI_INSTANCE_ID and TOKEN)
METRICS_ENABLED = bool(METRICS_INSTANCE_ID and TOKEN)

_loki_b64    = base64.b64encode(f"{LOKI_INSTANCE_ID}:{TOKEN}".encode()).decode()
_metrics_b64 = base64.b64encode(f"{METRICS_INSTANCE_ID}:{TOKEN}".encode()).decode()


# ── Loki log handler ──────────────────────────────────────────────────────────
class _LokiHandler(logging.Handler):
    _headers = {
        "Authorization": f"Basic {_loki_b64}",
        "Content-Type":  "application/json",
    }

    def emit(self, record: logging.LogRecord):
        if not LOKI_ENABLED:
            return
        try:
            payload = {
                "streams": [{
                    "stream": {
                        "app":   "myapp",        # <-- change to your app name
                        "level": record.levelname.lower(),
                        "env":   ENV,
                    },
                    "values": [[str(int(record.created * 1e9)), self.format(record)]],
                }]
            }
            threading.Thread(target=self._push, args=(payload,), daemon=True).start()
        except Exception:
            self.handleError(record)

    def _push(self, payload):
        try:
            _requests.post(LOKI_URL, data=json.dumps(payload),
                           headers=self._headers, timeout=5)
        except Exception:
            pass  # never crash because Loki is unreachable


def get_logger(name: str = "myapp") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s"))
    logger.addHandler(sh)

    lh = _LokiHandler()
    lh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(lh)
    return logger


# ── OTLP metrics ──────────────────────────────────────────────────────────────
_resource = Resource.create({"service.name": "myapp", "deployment.environment": ENV})

if METRICS_ENABLED:
    _exporter = OTLPMetricExporter(
        endpoint=f"{OTLP_ENDPOINT}/v1/metrics",
        headers={"Authorization": f"Basic {_metrics_b64}"},
    )
    _reader   = PeriodicExportingMetricReader(_exporter, export_interval_millis=30_000)
    _provider = MeterProvider(resource=_resource, metric_readers=[_reader])
else:
    _provider = MeterProvider(resource=_resource)   # no-op when creds missing

metrics.set_meter_provider(_provider)
_meter = metrics.get_meter("myapp")

# ── Instruments — use these in your routes ────────────────────────────────────
request_counter  = _meter.create_counter(
    "api_requests_total", description="Total HTTP requests", unit="1")
request_duration = _meter.create_histogram(
    "api_request_duration_seconds", description="Request duration", unit="s")

