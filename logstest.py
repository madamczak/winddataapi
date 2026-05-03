import requests
import time
import os

USER_ID = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
API_KEY = os.environ.get("GRAFANA_TOKEN", "")

logs = {"streams": [{"stream": {"Language": "Python", "source": "Code"}, "values": [[str(int(time.time()) * 1000000000), "This is my log line", ]]}]}


requests.post(url = "https://logs-prod-025.grafana.net/loki/api/v1/push",
              auth=(USER_ID, API_KEY),
              json=logs,
              headers={"Content-Type": "application/json"},
)