from __future__ import annotations

import json
import random as random_module
import time as time_module
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from .exceptions import ApiRequestError
from .telemetry import emit_event


_DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ApiClientConfig:
    api_base_url: str
    request_delay_seconds: float = 0.0
    max_retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_jitter_seconds: float = 0.25


@dataclass(frozen=True)
class RequestContext:
    run_id: str
    pi_id: str
    scenario: str
    stage: str


class WindDataApiClient:
    def __init__(
        self,
        config: ApiClientConfig,
        *,
        request_json: Callable[[str, float], dict[str, Any]] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        random_value: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._request_json = request_json or _default_request_json
        self._monotonic = monotonic or time_module.monotonic
        self._sleep = sleep or time_module.sleep
        self._random_value = random_value or random_module.random
        self._last_request_started_at: float | None = None

    def describe(self) -> dict[str, str | float | int]:
        return {
            "api_base_url": self.config.api_base_url,
            "request_delay_seconds": self.config.request_delay_seconds,
            "max_retries": self.config.max_retries,
            "backoff_base_seconds": self.config.backoff_base_seconds,
            "backoff_jitter_seconds": self.config.backoff_jitter_seconds,
        }

    def fetch_data_slice(
        self,
        *,
        farm: str,
        turbine: str,
        evaluated_window_start_utc: str,
        evaluated_window_end_utc: str,
        logger: object | None = None,
        context: RequestContext | None = None,
    ) -> dict[str, Any]:
        request_url = _build_query_url(
            self.config.api_base_url,
            farm=farm,
            turbine=turbine,
            start=evaluated_window_start_utc,
            end=evaluated_window_end_utc,
        )

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            self._enforce_request_spacing(logger=logger, context=context, request_url=request_url)
            try:
                payload = self._request_json(request_url, _DEFAULT_TIMEOUT_SECONDS)
                rows = payload.get("rows")
                if not isinstance(payload, dict) or not isinstance(rows, list):
                    raise ApiRequestError("Target API response must be a JSON object with a list 'rows' field")
                if logger is not None and context is not None:
                    emit_event(
                        logger,
                        "api_request_succeeded",
                        run_id=context.run_id,
                        pi_id=context.pi_id,
                        scenario=context.scenario,
                        stage=context.stage,
                        outcome="succeeded",
                        attempt=attempt,
                        row_count=len(rows),
                        farm=payload.get("farm", farm),
                        turbine=payload.get("turbine", turbine),
                    )
                return payload
            except ApiRequestError:
                raise
            except Exception as exc:
                if not _should_retry_request_error(exc):
                    if logger is not None and context is not None:
                        emit_event(
                            logger,
                            "api_request_failed",
                            run_id=context.run_id,
                            pi_id=context.pi_id,
                            scenario=context.scenario,
                            stage=context.stage,
                            outcome="failed",
                            attempts=attempt,
                            error=str(exc),
                        )
                    raise ApiRequestError(f"Target API request failed without retry eligibility: {exc}") from exc
                last_error = exc
                if attempt >= self.config.max_retries:
                    break

                backoff_seconds = self.config.backoff_base_seconds * (2 ** (attempt - 1))
                jitter_seconds = self.config.backoff_jitter_seconds * self._random_value()
                sleep_seconds = backoff_seconds + jitter_seconds
                if logger is not None and context is not None:
                    emit_event(
                        logger,
                        "api_retry",
                        run_id=context.run_id,
                        pi_id=context.pi_id,
                        scenario=context.scenario,
                        stage=context.stage,
                        outcome="retrying",
                        attempt=attempt,
                        max_retries=self.config.max_retries,
                        backoff_seconds=round(sleep_seconds, 6),
                        error=str(exc),
                    )
                self._sleep(sleep_seconds)

        if logger is not None and context is not None:
            emit_event(
                logger,
                "api_request_failed",
                run_id=context.run_id,
                pi_id=context.pi_id,
                scenario=context.scenario,
                stage=context.stage,
                outcome="failed",
                attempts=self.config.max_retries,
                error=str(last_error) if last_error is not None else "unknown API failure",
            )
        raise ApiRequestError(
            f"Exhausted {self.config.max_retries} attempts against target API"
            + (f": {last_error}" if last_error is not None else "")
        )

    def _enforce_request_spacing(
        self,
        *,
        logger: object | None,
        context: RequestContext | None,
        request_url: str,
    ) -> None:
        now = self._monotonic()
        if self._last_request_started_at is None:
            self._last_request_started_at = now
            return

        wait_seconds = self.config.request_delay_seconds - (now - self._last_request_started_at)
        if wait_seconds > 0:
            if logger is not None and context is not None:
                emit_event(
                    logger,
                    "api_request_delay",
                    run_id=context.run_id,
                    pi_id=context.pi_id,
                    scenario=context.scenario,
                    stage=context.stage,
                    outcome="waiting",
                    delay_seconds=round(wait_seconds, 6),
                    request_url=request_url,
                )
            self._sleep(wait_seconds)
            now = self._monotonic()
        self._last_request_started_at = now


def _build_query_url(api_base_url: str, *, farm: str, turbine: str, start: str, end: str) -> str:
    base_url = api_base_url.rstrip("/")
    path = f"/farms/{quote(farm, safe='')}/data/turbines/{quote(turbine, safe='')}/query"
    query = urlencode({"start": start, "end": end})
    return f"{base_url}{path}?{query}"


def _default_request_json(url: str, timeout_s: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ApiRequestError("Target API response must be a JSON object")
    return payload


def _should_retry_request_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 408 or exc.code == 429 or 500 <= exc.code < 600
    if isinstance(exc, (TimeoutError, URLError, OSError)):
        return True
    return False
