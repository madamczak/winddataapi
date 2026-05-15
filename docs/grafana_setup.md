# Grafana Connection
## Variables to set
```bash
GRAFANA_LOKI_INSTANCE_ID=123456        # Loki > Details > User
GRAFANA_METRICS_INSTANCE_ID=789012     # Prometheus > Details > User
GRAFANA_TOKEN=glc_eyJ...               # your token
GRAFANA_LOKI_URL=https://logs-prod-025.grafana.net/loki/api/v1/push   # Loki > Details > URL + /loki/api/v1/push
GRAFANA_OTLP_ENDPOINT=https://otlp-gateway-prod-eu-north-0.grafana.net/otlp  # OpenTelemetry > Configure > Endpoint
```
GRAFANA_LOKI_URL and GRAFANA_OTLP_ENDPOINT are already defaulted in the code - only set them if your stack is on a different region.
## Where to put them
**Docker:**
```bash
docker run -e GRAFANA_LOKI_INSTANCE_ID=123456 -e GRAFANA_METRICS_INSTANCE_ID=789012 -e GRAFANA_TOKEN=glc_eyJ... ...
```
**Raspberry Pi / bare metal** - add to ~/.bashrc or source a .env file in the runner script:
```bash
export GRAFANA_LOKI_INSTANCE_ID=123456
export GRAFANA_METRICS_INSTANCE_ID=789012
export GRAFANA_TOKEN=glc_eyJ...
export PI_ID=pi1   # optional, labels crawler logs
```
