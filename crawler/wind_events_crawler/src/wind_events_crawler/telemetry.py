from __future__ import annotations

import base64
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_LOKI_URL = "https://logs-prod-025.grafana.net/loki/api/v1/push"


@dataclass(frozen=True)
class TelemetrySettings:
    app_name: str
    environment: str
    loki_url: str
    loki_instance_id: str | None
    grafana_token: str | None
    pi_id: str | None
    source: str

    @property
    def loki_enabled(self) -> bool:
        return bool(self.loki_instance_id and self.grafana_token)


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _config_value(config: object | None, attribute: str) -> str | None:
    return _normalized_optional(getattr(config, attribute, None))


def _resolve_settings(*, config: object | None, source: str, app_name: str | None) -> TelemetrySettings:
    return TelemetrySettings(
        app_name=app_name or "wind_events_crawler",
        environment=_normalized_optional(os.environ.get("ENVIRONMENT")) or "production",
        loki_url=_config_value(config, "grafana_loki_url") or os.environ.get("GRAFANA_LOKI_URL") or DEFAULT_LOKI_URL,
        loki_instance_id=_config_value(config, "grafana_loki_instance_id") or os.environ.get("GRAFANA_LOKI_INSTANCE_ID"),
        grafana_token=_config_value(config, "grafana_token") or os.environ.get("GRAFANA_TOKEN"),
        pi_id=_config_value(config, "pi_id") or os.environ.get("PI_ID"),
        source=source,
    )


def _settings_signature(settings: TelemetrySettings) -> tuple[str, str, str, str | None, bool, str | None, str]:
    return (
        settings.app_name,
        settings.environment,
        settings.loki_url,
        settings.loki_instance_id,
        bool(settings.grafana_token),
        settings.pi_id,
        settings.source,
    )


def _send_loki_request(request: Request, timeout_s: int) -> None:
    with urlopen(request, timeout=timeout_s) as response:
        response.read()


def _push_loki_payload(payload: dict[str, Any], settings: TelemetrySettings) -> bool:
    if not settings.loki_enabled:
        return False

    credentials = base64.b64encode(f"{settings.loki_instance_id}:{settings.grafana_token}".encode("utf-8")).decode("ascii")
    request = Request(
        settings.loki_url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        _send_loki_request(request, timeout_s=5)
    except OSError:
        return False
    return True


def _parse_message(message: str) -> dict[str, Any]:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return {"message": message}
    if isinstance(payload, dict):
        return payload
    return {"message": message}


def _build_loki_payload(record: logging.LogRecord, settings: TelemetrySettings, message: str) -> dict[str, Any]:
    labels = {
        "app": settings.app_name,
        "env": settings.environment,
        "level": record.levelname.lower(),
        "source": settings.source,
    }
    if settings.pi_id:
        labels["pi_id"] = settings.pi_id

    return {
        "streams": [
            {
                "stream": labels,
                "values": [[str(int(record.created * 1_000_000_000)), json.dumps(_parse_message(message), sort_keys=True)]],
            }
        ]
    }


class _LokiHandler(logging.Handler):
    def __init__(self, settings: TelemetrySettings):
        super().__init__(level=logging.INFO)
        self._settings = settings

    def emit(self, record: logging.LogRecord) -> None:
        if not self._settings.loki_enabled:
            return
        try:
            message = self.format(record)
            payload = _build_loki_payload(record, self._settings, message)
            _push_loki_payload(payload, self._settings)
        except Exception:
            self.handleError(record)


def get_logger(
    name: str = "wind_events_crawler",
    *,
    config: object | None = None,
    source: str = "worker_runtime",
    app_name: str | None = None,
) -> logging.Logger:
    settings = _resolve_settings(config=config, source=source, app_name=app_name)
    logger = logging.getLogger(name)
    signature = _settings_signature(settings)
    if getattr(logger, "_wind_events_signature", None) == signature and logger.handlers:
        return logger

    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stdout_handler)

    loki_handler = _LokiHandler(settings)
    loki_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(loki_handler)
    logger._wind_events_signature = signature
    return logger


def emit_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, sort_keys=True))
