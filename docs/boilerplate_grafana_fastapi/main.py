"""
Minimal FastAPI + Grafana Cloud boilerplate.

Sends:
  - Logs  → Loki  (HTTP POST to GRAFANA_LOKI_URL)
  - Metrics → Mimir (OTLP HTTP to GRAFANA_OTLP_ENDPOINT)

Set these env vars before running:
  GRAFANA_LOKI_INSTANCE_ID
  GRAFANA_METRICS_INSTANCE_ID
  GRAFANA_TOKEN
"""

import time
import uvicorn
from fastapi import FastAPI, Request
from telemetry import get_logger, request_counter, request_duration

log = get_logger("myapp")
app = FastAPI()


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    request_counter.add(1, {
        "method":   request.method,
        "endpoint": request.url.path,
        "status":   str(response.status_code),
    })
    request_duration.record(duration, {
        "method": request.method,
        "status": str(response.status_code),
    })
    log.info(f"{request.method} {request.url.path} → {response.status_code}")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/hello")
def hello():
    log.info("hello endpoint called")
    return {"message": "Hello, Grafana!"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

