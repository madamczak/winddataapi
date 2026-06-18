from __future__ import annotations

import os
from datetime import datetime, timezone
from dataclasses import dataclass
import math
from pathlib import Path

from .exceptions import ConfigError


PACKAGE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "crawler" / "output" / "wind_events_crawler"
DEFAULT_RESULT_PATH = DEFAULT_OUTPUT_DIR / "wind_events_crawler.json"


@dataclass(frozen=True)
class WorkerConfig:
    api_base_url: str
    pi_id: str
    git_remote_name: str
    git_branch: str
    result_path: Path
    stale_lock_timeout_s: int
    grafana_loki_url: str | None
    grafana_loki_instance_id: str | None
    grafana_token: str | None
    request_delay_seconds: float = 2.0
    api_max_retries: int = 3
    api_backoff_base_seconds: float = 1.0
    api_backoff_jitter_seconds: float = 0.25
    scenario_farm: str = "kelmarsh"
    scenario_turbine: str = "turbine_1"
    scenario_window_start_utc: str = "1970-01-01T00:00:00Z"
    scenario_window_end_utc: str = "1970-01-01T00:10:00Z"

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        missing: list[str] = []
        api_base_url = os.environ.get("WINDDATA_API", "").strip()
        pi_id = os.environ.get("PI_ID", "").strip()
        scenario_farm = os.environ.get("SCENARIO_FARM", "").strip()
        scenario_turbine = os.environ.get("SCENARIO_TURBINE", "").strip()
        scenario_window_start_utc = os.environ.get("SCENARIO_WINDOW_START_UTC", "").strip()
        scenario_window_end_utc = os.environ.get("SCENARIO_WINDOW_END_UTC", "").strip()

        if not api_base_url:
            missing.append("WINDDATA_API")
        if not pi_id:
            missing.append("PI_ID")
        if not scenario_farm:
            missing.append("SCENARIO_FARM")
        if not scenario_turbine:
            missing.append("SCENARIO_TURBINE")
        if not scenario_window_start_utc:
            missing.append("SCENARIO_WINDOW_START_UTC")
        if not scenario_window_end_utc:
            missing.append("SCENARIO_WINDOW_END_UTC")
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

        result_path_value = os.environ.get("WIND_EVENTS_RESULT_PATH", "").strip()
        result_path = Path(result_path_value) if result_path_value else DEFAULT_RESULT_PATH
        stale_lock_timeout_value = os.environ.get("STALE_LOCK_TIMEOUT_S", "1800").strip() or "1800"
        try:
            stale_lock_timeout_s = int(stale_lock_timeout_value)
        except ValueError as exc:
            raise ConfigError("STALE_LOCK_TIMEOUT_S must be an integer") from exc
        if stale_lock_timeout_s <= 0:
            raise ConfigError("STALE_LOCK_TIMEOUT_S must be greater than zero")

        request_delay_seconds = _read_non_negative_float("REQUEST_DELAY_S", default=2.0)
        api_max_retries = _read_positive_int("API_MAX_RETRIES", default=3)
        api_backoff_base_seconds = _read_positive_float("API_BACKOFF_BASE_S", default=1.0)
        api_backoff_jitter_seconds = _read_non_negative_float("API_BACKOFF_JITTER_S", default=0.25)
        _validate_window_bounds(
            start_utc=scenario_window_start_utc,
            end_utc=scenario_window_end_utc,
        )

        return cls(
            api_base_url=api_base_url.rstrip("/"),
            pi_id=pi_id,
            git_remote_name=os.environ.get("GIT_REMOTE_NAME", "origin").strip() or "origin",
            git_branch=os.environ.get("GIT_BRANCH", "main").strip() or "main",
            result_path=result_path,
            stale_lock_timeout_s=stale_lock_timeout_s,
            grafana_loki_url=os.environ.get("GRAFANA_LOKI_URL") or None,
            grafana_loki_instance_id=os.environ.get("GRAFANA_LOKI_INSTANCE_ID") or None,
            grafana_token=os.environ.get("GRAFANA_TOKEN") or None,
            request_delay_seconds=request_delay_seconds,
            api_max_retries=api_max_retries,
            api_backoff_base_seconds=api_backoff_base_seconds,
            api_backoff_jitter_seconds=api_backoff_jitter_seconds,
            scenario_farm=scenario_farm,
            scenario_turbine=scenario_turbine,
            scenario_window_start_utc=scenario_window_start_utc,
            scenario_window_end_utc=scenario_window_end_utc,
        )


def _read_positive_int(name: str, *, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip() or str(default)
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def _read_positive_float(name: str, *, default: float) -> float:
    parsed = _read_non_negative_float(name, default=default)
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def _read_non_negative_float(name: str, *, default: float) -> float:
    raw_value = os.environ.get(name, str(default)).strip() or str(default)
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if not math.isfinite(parsed):
        raise ConfigError(f"{name} must be a finite number")
    if parsed < 0:
        raise ConfigError(f"{name} must be greater than or equal to zero")
    return parsed


def _validate_window_bounds(*, start_utc: str, end_utc: str) -> None:
    start_dt = _parse_utc_timestamp("SCENARIO_WINDOW_START_UTC", start_utc)
    end_dt = _parse_utc_timestamp("SCENARIO_WINDOW_END_UTC", end_utc)
    if end_dt <= start_dt:
        raise ConfigError("SCENARIO_WINDOW_END_UTC must be later than SCENARIO_WINDOW_START_UTC")


def _parse_utc_timestamp(name: str, value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfigError(f"{name} must be an ISO 8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ConfigError(f"{name} must be an ISO 8601 UTC timestamp")
    return parsed
