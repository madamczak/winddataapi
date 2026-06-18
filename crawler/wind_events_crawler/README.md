# wind_events_crawler

Standalone uv-packaged worker foundation for the winddataAPI crawler fleet.

## Purpose

This subproject provides the packaged boundary for the future headless worker that:

- loads validated runtime configuration
- reserves the shared artifact contract
- exposes a stable entrypoint for runner scripts
- keeps worker code isolated from the root API and legacy crawler dependencies

## Local bootstrap

```powershell
python -m uv sync --directory .
python -m uv run --directory . wind-events-crawler
```

The first runnable foundation step creates or preserves the placeholder result artifact at:

`..\output\wind_events_crawler\wind_events_crawler.json`
