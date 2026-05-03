"""
weather.py — OpenWeatherMap One Call 3.0 Time Machine integration.

One request per farm per calendar hour.
Results are cached in-memory within a single run, and optionally persisted
to weather_cache.json on disk (--cache-weather flag).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OWM_URL = "https://api.openweathermap.org/data/3.0/onecall/timemachine"
WEATHER_CACHE_FILE = "weather_cache.json"


class WeatherClient:
    def __init__(
        self,
        api_key: str,
        use_disk_cache: bool = False,
        cache_path: str = WEATHER_CACHE_FILE,
    ) -> None:
        self.api_key = api_key
        self.use_disk_cache = use_disk_cache
        self.cache_path = Path(cache_path)
        # in-memory cache: key = "{farm}_{hour_start_iso}"
        self._cache: dict[str, dict] = {}
        if use_disk_cache and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                logger.info("Loaded %d entries from weather disk cache.", len(self._cache))
            except Exception as exc:
                logger.warning("Could not load weather cache: %s", exc)

    # ------------------------------------------------------------------
    def fetch(self, farm: str, lat: float, lon: float, hour_start_iso: str) -> dict:
        """
        Return a weather snapshot dict for the given farm + hour.
        Falls back to weather_missing=True on any error.
        """
        cache_key = f"{farm}_{hour_start_iso}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        dt_unix = int(
            time.mktime(
                time.strptime(hour_start_iso, "%Y-%m-%d %H:%M:%S")
            )
        )

        try:
            resp = httpx.get(
                OWM_URL,
                params={
                    "lat": lat,
                    "lon": lon,
                    "dt": dt_unix,
                    "appid": self.api_key,
                    "units": "metric",
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            snapshot = _parse_owm(payload)
        except Exception as exc:
            logger.warning("OWM fetch failed for %s @ %s: %s", farm, hour_start_iso, exc)
            snapshot = _missing_weather()

        self._cache[cache_key] = snapshot
        return snapshot

    def flush_cache(self) -> None:
        """Persist in-memory cache to disk if disk caching is enabled."""
        if self.use_disk_cache:
            try:
                self.cache_path.write_text(
                    json.dumps(self._cache, indent=2), encoding="utf-8"
                )
                logger.info("Weather cache saved (%d entries).", len(self._cache))
            except Exception as exc:
                logger.warning("Could not save weather cache: %s", exc)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_owm(payload: dict) -> dict:
    """Extract the fields we care about from an OWM timemachine response."""
    # One Call 3.0 timemachine returns data under payload["data"][0]
    data: dict[str, Any] = {}
    if "data" in payload and payload["data"]:
        data = payload["data"][0]
    elif "current" in payload:
        # Some versions return "current" instead
        data = payload["current"]

    weather_list = data.get("weather", [{}])
    w = weather_list[0] if weather_list else {}

    rain = data.get("rain") or {}
    snow = data.get("snow") or {}

    return {
        "source": "openweathermap",
        "temp": data.get("temp"),
        "feels_like": data.get("feels_like"),
        "pressure": data.get("pressure"),
        "humidity": data.get("humidity"),
        "dew_point": data.get("dew_point"),
        "clouds": data.get("clouds"),
        "visibility": data.get("visibility"),
        "wind_speed": data.get("wind_speed"),
        "wind_deg": data.get("wind_deg"),
        "wind_gust": data.get("wind_gust"),
        "condition": w.get("main"),
        "condition_detail": w.get("description"),
        "rain_1h": rain.get("1h", 0.0),
        "snow_1h": snow.get("1h", 0.0),
        "uvi": data.get("uvi"),
        "weather_missing": False,
    }


def _missing_weather() -> dict:
    return {
        "source": "openweathermap",
        "temp": None,
        "feels_like": None,
        "pressure": None,
        "humidity": None,
        "dew_point": None,
        "clouds": None,
        "visibility": None,
        "wind_speed": None,
        "wind_deg": None,
        "wind_gust": None,
        "condition": None,
        "condition_detail": None,
        "rain_1h": None,
        "snow_1h": None,
        "uvi": None,
        "weather_missing": True,
    }

