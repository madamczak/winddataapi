---
title: 'Enable Grafana logging for worker foundation tests'
type: 'feature'
created: '2026-06-15T19:20:07.689+02:00'
status: 'done'
baseline_commit: 'f34e3cd61dbccaf0ef48cfc79b024dee8b8a2735'
context:
  - '{project-root}/tests/test_with_grafana_logging.py'
  - '{project-root}/grafana_telemetry.py'
  - '{project-root}/env_loader.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `tests\wind_events_crawler\test_config.py` currently validates the worker foundation locally but does not emit Loki logs or OTLP metrics, so its execution is invisible in Grafana even though the repository already has Grafana-enabled pytest examples and a repo-level `.env` loader.

**Approach:** Add lightweight, non-breaking Grafana test instrumentation to the worker test path by reusing the existing env-driven Loki and metrics conventions, while preserving the tests’ core assertions and keeping Grafana failures non-fatal.

## Boundaries & Constraints

**Always:** Reuse the existing `.env`-driven Grafana configuration model; keep test assertions intact; make telemetry best-effort so missing Grafana creds or push failures never fail the worker tests; keep labels compatible with current Loki querying patterns (`source="pytest"` / app-level grouping) and avoid introducing secrets into source files.

**Ask First:** Add any new third-party dependency beyond what the repository already uses for test telemetry; change the existing Grafana label taxonomy in a way that would break current dashboards or queries.

**Never:** Hardcode Grafana credentials; remove or weaken the import-safety assertions in `tests\wind_events_crawler\test_config.py`; require network access for the tests to pass; move the worker tests out of `tests\wind_events_crawler\`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Worker test run with Grafana env present | `.env` contains valid Loki/OTLP settings and `pytest tests\wind_events_crawler\test_config.py` is executed | Test lifecycle logs and test metrics are emitted for the worker test file, and the tests still pass locally | Telemetry push failures are logged to stdout/stderr only; test result remains based on assertions |
| Worker test run without Grafana env | Missing or empty Grafana env vars | Worker tests still execute and pass without raising telemetry setup exceptions | Telemetry becomes a no-op or best-effort fallback |
| Import-safety test | Import-side-effect guard monkeypatches block network / subprocess calls during module import | Grafana instrumentation must not trigger import-time network/Git work inside worker modules under test | If telemetry setup is attempted too early, the test should still catch and fail that behavior |

</frozen-after-approval>

## Code Map

- `tests\wind_events_crawler\test_config.py` -- target worker foundation tests that need Grafana lifecycle logging
- `tests\test_with_grafana_logging.py` -- existing example of autouse Loki logging + OTLP metrics for pytest
- `grafana_telemetry.py` -- repo telemetry helper already reading `.env` via `env_loader.py`
- `env_loader.py` -- shared repo-level `.env` loader for local test execution

## Tasks & Acceptance

**Execution:**
- [x] `tests\wind_events_crawler\test_config.py` -- add worker-test Grafana logging/metrics hooks around the existing tests, ideally via shared helpers or a local autouse fixture, so each test emits start/finish lifecycle events without changing its assertions
- [x] `tests\wind_events_crawler\test_config.py` -- keep Grafana telemetry optional and non-fatal when env vars are absent or pushes fail, mirroring the behavior of `tests\test_with_grafana_logging.py`
- [x] `tests\wind_events_crawler\test_config.py` -- make the Grafana-emitting test path distinguishable in Loki/Grafana from the generic sample tests, while staying query-friendly
- [x] `tests\test_with_grafana_logging.py` and/or shared helper code if needed -- extract or reuse common telemetry behavior only if it reduces duplication without destabilizing the existing Grafana sample suite
- [x] `tests\wind_events_crawler\test_config.py` -- verify the worker tests still cover config validation, artifact placeholder shape, and import safety after instrumentation

**Acceptance Criteria:**
- Given valid Grafana env values in the repo `.env`, when `python -m pytest -q tests\wind_events_crawler\test_config.py` runs, then the worker test lifecycle emits Loki logs and OTLP metrics without changing pass/fail semantics.
- Given missing or invalid Grafana env values, when the same worker tests run, then the tests still complete based on their assertions and telemetry failures do not fail the suite.
- Given the import-safety test monkeypatches network and subprocess access, when worker modules are imported during the test, then the assertions still guard against import-time side effects and the added test instrumentation does not interfere with that protection.

## Spec Change Log

## Design Notes

- Prefer adding telemetry around the pytest lifecycle, not inside the worker modules under test. The worker modules should remain import-safe and unaware of test-only logging.
- If duplication is minimal, keeping worker-test-specific telemetry local to `tests\wind_events_crawler\test_config.py` is acceptable and lower risk than aggressively refactoring the existing sample test file.

## Verification

**Commands:**
- `python -m pytest -q tests\wind_events_crawler\test_config.py` -- expected: all worker foundation tests pass and emit Grafana lifecycle logs when env vars are present
- `python -m pytest -q tests\test_with_grafana_logging.py -k test_addition` -- expected: existing Grafana sample path still works after any shared-helper reuse

## Suggested Review Order

**Worker test telemetry wiring**

- Worker-test-specific pytest plugin now owns lifecycle logging and metrics.
  [`conftest.py:1`](../../tests/wind_events_crawler/conftest.py#L1)

- Loki payload labels distinguish this suite from the generic Grafana sample tests.
  [`conftest.py:46`](../../tests/wind_events_crawler/conftest.py#L46)

- Fixture teardown now classifies pass/fail/skip from registered pytest reports.
  [`conftest.py:91`](../../tests/wind_events_crawler/conftest.py#L91)

- Metrics flush is now best-effort, so telemetry outages do not fail teardown.
  [`conftest.py:125`](../../tests/wind_events_crawler/conftest.py#L125)

**Worker test assertions preserved**

- The worker foundation assertions remain focused on config, artifact shape, and import safety.
  [`test_config.py:1`](../../tests/wind_events_crawler/test_config.py#L1)

**Shared env-driven telemetry path**

- Repo-level `.env` loading stays centralized and reusable across test suites.
  [`env_loader.py:1`](../../env_loader.py#L1)

- OTLP telemetry now reads the repo `.env` before building exporters.
  [`grafana_telemetry.py:23`](../../grafana_telemetry.py#L23)

- The existing Grafana sample pytest suite was aligned to the same `.env` bootstrapping.
  [`test_with_grafana_logging.py:12`](../../tests/test_with_grafana_logging.py#L12)

- The Playwright/Loki test config no longer hardcodes credentials in source.
  [`config.py:1`](../../tests/wind_data_tests/config.py#L1)
