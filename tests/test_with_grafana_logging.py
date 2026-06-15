"""
Pytest examples with Grafana Loki logging + OTLP metrics.
Logs  → Grafana Cloud Loki  (HTTP push)
Metrics → Grafana Cloud Mimir (OTLP via grafana_telemetry.py)
"""
import sys
import os
import time
import requests
import pytest

from env_loader import load_repo_env

load_repo_env()

# Allow importing grafana_telemetry from the project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from grafana_telemetry import (
    tests_passed_counter, tests_failed_counter, tests_run_counter,
    test_duration_histogram, set_rotor_speed, set_power, flush_metrics, timer,
)

# ── Grafana Loki credentials ──────────────────────────────────────────────────
# Set GRAFANA_LOKI_INSTANCE_ID, GRAFANA_TOKEN, GRAFANA_LOKI_URL as env vars.
import os
LOKI_URL  = os.environ.get("GRAFANA_LOKI_URL",  "https://logs-prod-025.grafana.net/loki/api/v1/push")
USER_ID   = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
API_KEY   = os.environ.get("GRAFANA_TOKEN", "")


# ── Loki helper ───────────────────────────────────────────────────────────────

def loki_push(message: str, level: str = "info", test_name: str = "unknown",
              status: str = "running") -> None:
    """Send a single log line to Grafana Loki."""
    payload = {
        "streams": [
            {
                "stream": {
                    "source":    "pytest",
                    "app":       "winddataAPI",
                    "level":     level,
                    "test":      test_name,
                    "status":    status,
                },
                "values": [
                    [str(int(time.time()) * 1_000_000_000), message]
                ],
            }
        ]
    }
    try:
        resp = requests.post(
            url=LOKI_URL,
            auth=(USER_ID, API_KEY),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Never let logging break the test
        print(f"[loki] failed to push log: {exc}")


# ── Fixture: log every test start / pass / fail ───────────────────────────────

@pytest.fixture(autouse=True)
def grafana_log(request):
    """Automatically log test lifecycle to Grafana Loki + record metrics."""
    name = request.node.name
    loki_push(f"TEST STARTED: {name}", level="info", test_name=name, status="started")
    _start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - _start

    rep = getattr(request.node, "_grafana_rep", None)
    if rep is not None:
        outcome = "passed" if rep.passed else ("failed" if rep.failed else "error")
        level   = "info"   if rep.passed else "error"
    else:
        outcome = "passed"
        level   = "info"

    # ── Loki log ──────────────────────────────────────────────────────────────
    loki_push(f"TEST {outcome.upper()}: {name} ({elapsed:.3f}s)",
              level=level, test_name=name, status=outcome)

    # ── OTLP metrics ──────────────────────────────────────────────────────────
    attrs = {"test": name, "status": outcome}
    tests_run_counter.add(1, attrs)
    test_duration_histogram.record(elapsed, attrs)
    if outcome == "passed":
        tests_passed_counter.add(1, attrs)
    else:
        tests_failed_counter.add(1, attrs)


@pytest.fixture(scope="session", autouse=True)
def flush_at_end():
    """Force-flush all OTLP metrics to Grafana at end of the test session."""
    yield
    flush_metrics()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach the call-phase report to the item so the fixture can read it."""
    outcome = yield
    rep = outcome.get_result()
    if call.when == "call":
        item._grafana_rep = rep


# ── Sample tests ──────────────────────────────────────────────────────────────

class TestBasicMath:
    """Simple arithmetic – always pass, good for smoke-testing the pipeline."""

    def test_addition(self):
        loki_push("Checking 2 + 2 = 4", test_name="test_addition")
        result = 2 + 2
        loki_push(f"Result: {result}", test_name="test_addition")
        assert result == 4

    def test_subtraction(self):
        loki_push("Checking 10 - 3 = 7", test_name="test_subtraction")
        result = 10 - 3
        loki_push(f"Result: {result}", test_name="test_subtraction")
        assert result == 7

    def test_division_by_zero(self):
        """Expected to raise – logged as a pass because we assert the exception."""
        loki_push("Expecting ZeroDivisionError", test_name="test_division_by_zero")
        with pytest.raises(ZeroDivisionError):
            _ = 1 / 0
        loki_push("ZeroDivisionError raised as expected", test_name="test_division_by_zero")


class TestLokiConnectivity:
    """Verify we can actually reach Grafana Loki."""

    def test_loki_push_returns_204(self):
        loki_push("Sending connectivity probe to Loki", test_name="test_loki_push_returns_204")
        response = requests.post(
            url=LOKI_URL,
            auth=(USER_ID, API_KEY),
            json={
                "streams": [{
                    "stream": {"source": "pytest", "app": "winddataAPI", "level": "info"},
                    "values": [[str(int(time.time()) * 1_000_000_000),
                                "connectivity probe from pytest"]],
                }]
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        loki_push(f"Loki responded with HTTP {response.status_code}",
                  test_name="test_loki_push_returns_204")
        assert response.status_code == 204, (
            f"Expected 204 No Content from Loki, got {response.status_code}: {response.text}"
        )


class TestWindDataHelpers:
    """Unit tests for wind-data domain logic."""

    def test_rotor_speed_in_rated_range(self):
        name = "test_rotor_speed_in_rated_range"
        rated_min, rated_max = 14.8, 15.2
        sample_speeds = [14.9, 15.0, 15.1, 15.05]
        loki_push(f"Testing {len(sample_speeds)} rotor speed samples against rated range "
                  f"[{rated_min}, {rated_max}]", test_name=name)
        with timer(name):
            for speed in sample_speeds:
                set_rotor_speed(speed)           # update gauge → Mimir
                loki_push(f"  speed={speed} in_range={rated_min <= speed <= rated_max}",
                          test_name=name)
                assert rated_min <= speed <= rated_max, f"Speed {speed} outside rated range"
        loki_push("All samples within rated range ✓", test_name=name)

    def test_power_positive_when_wind_above_cut_in(self):
        name = "test_power_positive_when_wind_above_cut_in"
        cut_in = 3.0
        data = [
            {"wind": 5.0,  "power": 300.0},
            {"wind": 8.0,  "power": 900.0},
            {"wind": 12.0, "power": 2000.0},
        ]
        loki_push(f"Checking power > 0 for {len(data)} data points above cut-in ({cut_in} m/s)",
                  test_name=name)
        with timer(name):
            for point in data:
                set_power(point["power"])        # update gauge → Mimir
                loki_push(f"  wind={point['wind']} m/s → power={point['power']} kW",
                          test_name=name)
                assert point["wind"] > cut_in,   "Wind speed below cut-in"
                assert point["power"] > 0,       "Power should be positive above cut-in"
        loki_push("All power values positive ✓", test_name=name)

    @pytest.mark.parametrize("wind,expected_label", [
        (1.5,  "below_cut_in"),
        (6.0,  "partial_load"),
        (12.0, "rated"),
        (25.1, "above_cut_out"),
    ])
    def test_wind_regime_classification(self, wind, expected_label):
        name = f"test_wind_regime_classification[{wind}]"
        loki_push(f"Classifying wind={wind} m/s, expecting '{expected_label}'",
                  test_name=name)

        def classify(w):
            if w < 3.0:   return "below_cut_in"
            if w < 10.0:  return "partial_load"
            if w <= 25.0: return "rated"
            return "above_cut_out"

        label = classify(wind)
        loki_push(f"  → classified as '{label}'", test_name=name)
        assert label == expected_label


# ── Deliberately failing tests ────────────────────────────────────────────────

class TestFailingExamples:
    """
    These tests are INTENTIONALLY failing to demonstrate how failures appear
    in Grafana Loki with level=error and status=failed.
    Mark them with xfail so the suite still exits green.
    """

    @pytest.mark.xfail(strict=True, reason="intentional: wrong expected value")
    def test_wrong_power_calculation(self):
        name = "test_wrong_power_calculation"
        loki_push("Calculating power — using wrong formula intentionally",
                  test_name=name)
        wind_speed = 10.0
        # Correct formula would use 0.5 * rho * A * v^3, but we use v^2 on purpose
        power = wind_speed ** 2
        loki_push(f"Computed power={power} kW (expected ~2000 kW)", test_name=name,
                  level="warn")
        assert power == 2000.0, f"Power {power} != 2000 kW — formula is wrong"

    @pytest.mark.xfail(strict=True, reason="intentional: rotor speed outside rated band")
    def test_rotor_speed_out_of_range(self):
        name = "test_rotor_speed_out_of_range"
        rated_min, rated_max = 14.8, 15.2
        bad_speed = 13.5
        loki_push(f"Checking rotor speed {bad_speed} RPM against rated [{rated_min}, {rated_max}]",
                  test_name=name, level="warn")
        in_range = rated_min <= bad_speed <= rated_max
        loki_push(f"in_range={in_range} — expected True, got False", test_name=name,
                  level="error")
        assert in_range, f"Rotor speed {bad_speed} is outside rated range!"

    @pytest.mark.xfail(strict=True, reason="intentional: negative power makes no sense")
    def test_negative_power_rejected(self):
        name = "test_negative_power_rejected"
        loki_push("Simulating a sensor glitch returning negative power",
                  test_name=name, level="warn")
        faulty_power = -150.0

        def validate_power(p):
            return p >= 0

        valid = validate_power(faulty_power)
        loki_push(f"validate_power({faulty_power}) = {valid} — should be True",
                  test_name=name, level="error")
        assert valid, f"Power value {faulty_power} kW is invalid (negative)"

    @pytest.mark.xfail(strict=True, reason="intentional: API returns unexpected status")
    def test_api_unexpected_status(self):
        name = "test_api_unexpected_status"
        loki_push("Simulating API returning 500 instead of 200", test_name=name,
                  level="warn")
        # Simulate what would happen with a bad response code
        simulated_status_code = 500
        loki_push(f"API returned HTTP {simulated_status_code}", test_name=name,
                  level="error")
        assert simulated_status_code == 200, (
            f"Expected HTTP 200 from API, got {simulated_status_code} — server error!"
        )

    @pytest.mark.xfail(strict=True, reason="intentional: wind speed cannot be negative")
    def test_invalid_wind_speed_negative(self):
        name = "test_invalid_wind_speed_negative"
        loki_push("Ingesting a data point with negative wind speed from DB",
                  test_name=name, level="warn")
        wind_speed = -5.0

        def is_valid_wind(w):
            return 0.0 <= w <= 40.0

        valid = is_valid_wind(wind_speed)
        loki_push(f"is_valid_wind({wind_speed}) = {valid}", test_name=name,
                  level="error")
        assert valid, f"Wind speed {wind_speed} m/s is physically impossible"

