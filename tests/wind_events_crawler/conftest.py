from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import requests

from env_loader import load_repo_env


REPO_ROOT = Path(__file__).resolve().parents[2]
load_repo_env(REPO_ROOT / ".env")

LOKI_URL = os.environ.get("GRAFANA_LOKI_URL", "https://logs-prod-025.grafana.net/loki/api/v1/push")
USER_ID = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
API_KEY = os.environ.get("GRAFANA_TOKEN", "")
WORKER_TEST_APP = os.environ.get("GRAFANA_WORKER_TEST_APP_NAME", "wind_events_crawler_tests")


def _load_metrics_backend():
    try:
        from grafana_telemetry import (
            flush_metrics,
            test_duration_histogram,
            tests_failed_counter,
            tests_passed_counter,
            tests_run_counter,
        )
    except Exception:
        return None

    return {
        "flush_metrics": flush_metrics,
        "test_duration_histogram": test_duration_histogram,
        "tests_failed_counter": tests_failed_counter,
        "tests_passed_counter": tests_passed_counter,
        "tests_run_counter": tests_run_counter,
    }


METRICS_BACKEND = _load_metrics_backend()


def loki_push(message: str, *, level: str = "info", test_name: str = "unknown", status: str = "running") -> None:
    if not (USER_ID and API_KEY):
        return

    payload = {
        "streams": [
            {
                "stream": {
                    "source": "pytest",
                    "app": WORKER_TEST_APP,
                    "suite": "wind_events_crawler",
                    "level": level,
                    "test": test_name,
                    "status": status,
                },
                "values": [[str(int(time.time()) * 1_000_000_000), message]],
            }
        ]
    }
    try:
        response = requests.post(
            url=LOKI_URL,
            auth=(USER_ID, API_KEY),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[loki] failed to push worker test log: {exc}")


@pytest.fixture(autouse=True)
def grafana_log_worker_tests(request: pytest.FixtureRequest):
    test_name = request.node.name
    loki_push(
        f"WORKER TEST STARTED: {test_name}",
        level="info",
        test_name=test_name,
        status="started",
    )
    started_at = time.perf_counter()
    yield
    elapsed = time.perf_counter() - started_at

    reports = getattr(request.node, "_worker_reports", {})
    report = reports.get("call") or reports.get("setup") or reports.get("teardown")
    if report is None:
        outcome = "passed"
        level = "info"
    elif report.skipped:
        outcome = "skipped"
        level = "warning"
    elif report.passed:
        outcome = "passed"
        level = "info"
    else:
        outcome = "failed"
        level = "error"

    loki_push(
        f"WORKER TEST {outcome.upper()}: {test_name} ({elapsed:.3f}s)",
        level=level,
        test_name=test_name,
        status=outcome,
    )

    if METRICS_BACKEND is None:
        return

    attrs = {"test": test_name, "status": outcome, "suite": "wind_events_crawler"}
    METRICS_BACKEND["tests_run_counter"].add(1, attrs)
    METRICS_BACKEND["test_duration_histogram"].record(elapsed, attrs)
    if outcome == "passed":
        METRICS_BACKEND["tests_passed_counter"].add(1, attrs)
    else:
        METRICS_BACKEND["tests_failed_counter"].add(1, attrs)


@pytest.fixture(scope="session", autouse=True)
def flush_worker_metrics_at_end():
    yield
    if METRICS_BACKEND is not None:
        try:
            METRICS_BACKEND["flush_metrics"]()
        except Exception as exc:
            print(f"[metrics] flush failed: {exc}")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    reports = getattr(item, "_worker_reports", {})
    reports[call.when] = report
    item._worker_reports = reports
