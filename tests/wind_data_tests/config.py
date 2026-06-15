from __future__ import annotations

import os

from env_loader import load_repo_env

load_repo_env()

APP_NAME = os.environ.get("GRAFANA_TEST_APP_NAME", "wind_data_tests")
LOKI_INSTANCE_ID = os.environ.get("GRAFANA_LOKI_INSTANCE_ID", "")
TOKEN = os.environ.get("GRAFANA_TOKEN", "")
