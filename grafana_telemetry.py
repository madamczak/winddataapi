"""
Grafana Cloud telemetry helper — metrics via OpenTelemetry OTLP.

Provides:
  - meter / counters / histograms ready to use in tests or app code
  - flush_metrics() — call at end of a test session to force-export

Grafana Cloud OTLP endpoint (Mimir for metrics):
  https://otlp-gateway-prod-eu-north-0.grafana.net/otlp

Auth: Basic  <instance_id>:<token>
"""

import base64
import time
import os
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

from env_loader import load_repo_env

load_repo_env()

# ── Grafana Cloud credentials ─────────────────────────────────────────────────
# Set these as environment variables (never hard-code tokens in source):
#   GRAFANA_LOKI_INSTANCE_ID   — found under "Hosted Logs" in your Grafana stack
#   GRAFANA_METRICS_INSTANCE_ID — found under "Hosted Metrics" (= stack ID)
#   GRAFANA_TOKEN               — Access Policy token with logs:write + metrics:write
GRAFANA_LOKI_INSTANCE_ID    = os.environ.get("GRAFANA_LOKI_INSTANCE_ID",    "")
GRAFANA_METRICS_INSTANCE_ID = os.environ.get("GRAFANA_METRICS_INSTANCE_ID", "")
GRAFANA_TOKEN               = os.environ.get("GRAFANA_TOKEN",               "")
OTLP_ENDPOINT               = os.environ.get("GRAFANA_OTLP_ENDPOINT",
                                "https://otlp-gateway-prod-eu-north-0.grafana.net/otlp")

# ── Build Basic-auth header for Mimir (metrics:write token) ──────────────────
_creds  = f"{GRAFANA_METRICS_INSTANCE_ID}:{GRAFANA_TOKEN}".encode()
_b64    = base64.b64encode(_creds).decode()
OTLP_HEADERS = {"Authorization": f"Basic {_b64}"}

# ── OTLP exporter → Grafana Cloud Mimir ──────────────────────────────────────
_exporter = OTLPMetricExporter(
    endpoint=f"{OTLP_ENDPOINT}/v1/metrics",
    headers=OTLP_HEADERS,
)

# Export every 10 minutes
_reader = PeriodicExportingMetricReader(_exporter, export_interval_millis=600_000)

_resource = Resource.create({
    "service.name":    "winddataAPI",
    "service.version": "1.0.0",
    "deployment.environment": "development",
})

_provider = MeterProvider(resource=_resource, metric_readers=[_reader])
metrics.set_meter_provider(_provider)

# ── Public meter ─────────────────────────────────────────────────────────────
meter = metrics.get_meter("winddataAPI.tests")

# ── Pre-built instruments ─────────────────────────────────────────────────────
# Counters
tests_passed_counter = meter.create_counter(
    name="tests_passed_total",
    description="Total number of passing pytest tests",
    unit="1",
)
tests_failed_counter = meter.create_counter(
    name="tests_failed_total",
    description="Total number of failing pytest tests",
    unit="1",
)
tests_run_counter = meter.create_counter(
    name="tests_run_total",
    description="Total number of pytest tests executed",
    unit="1",
)

# Histograms
test_duration_histogram = meter.create_histogram(
    name="test_duration_seconds",
    description="Time taken to execute each test (seconds)",
    unit="s",
)

# Wind-data domain gauges (Observable — set via callback)
_rotor_speed_value: float = 0.0
_power_value:       float = 0.0

def _observe_rotor_speed(options):
    yield metrics.Observation(_rotor_speed_value, {"farm": "kelmarsh", "turbine": "turbine_2"})

def _observe_power(options):
    yield metrics.Observation(_power_value, {"farm": "kelmarsh", "turbine": "turbine_2"})

rotor_speed_gauge = meter.create_observable_gauge(
    name="wind_rotor_speed_rpm",
    callbacks=[_observe_rotor_speed],
    description="Last observed rotor speed (RPM) in tests",
    unit="RPM",
)
power_gauge = meter.create_observable_gauge(
    name="wind_power_kw",
    callbacks=[_observe_power],
    description="Last observed power output (kW) in tests",
    unit="kW",
)


def set_rotor_speed(value: float) -> None:
    """Update the rotor speed observable gauge value."""
    global _rotor_speed_value
    _rotor_speed_value = value


def set_power(value: float) -> None:
    """Update the power observable gauge value."""
    global _power_value
    _power_value = value


def flush_metrics() -> None:
    """Force-flush all pending metrics to Grafana Cloud."""
    _provider.force_flush(timeout_millis=10_000)


# ── Convenience timer context manager ────────────────────────────────────────
class timer:
    """
    Usage:
        with timer("test_name") as t:
            ... do work ...
        # t.elapsed_seconds is available after the block
    """
    def __init__(self, test_name: str, extra_attrs: dict | None = None):
        self.test_name   = test_name
        self.extra_attrs = extra_attrs or {}
        self.elapsed_seconds: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_seconds = time.perf_counter() - self._start
        attrs = {"test": self.test_name, **self.extra_attrs}
        test_duration_histogram.record(self.elapsed_seconds, attrs)
        return False   # don't suppress exceptions
