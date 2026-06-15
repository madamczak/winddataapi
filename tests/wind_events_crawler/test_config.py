from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from env_loader import load_repo_env

load_repo_env()

WORKER_SRC = REPO_ROOT / "crawler" / "wind_events_crawler" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))


def _reload_module(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_worker_config_requires_required_environment_variables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WINDDATA_API", raising=False)
    monkeypatch.delenv("PI_ID", raising=False)

    config_module = _reload_module("wind_events_crawler.config")

    with pytest.raises(config_module.ConfigError) as exc_info:
        config_module.WorkerConfig.from_env()

    message = str(exc_info.value)
    assert "WINDDATA_API" in message
    assert "PI_ID" in message


def test_worker_config_applies_defaults_and_reserves_result_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WINDDATA_API", "https://example.test")
    monkeypatch.setenv("PI_ID", "pi-test")

    config_module = _reload_module("wind_events_crawler.config")

    config = config_module.WorkerConfig.from_env()

    assert config.api_base_url == "https://example.test"
    assert config.pi_id == "pi-test"
    assert config.git_remote_name == "origin"
    assert config.git_branch == "main"
    assert config.result_path == REPO_ROOT / "crawler" / "output" / "wind_events_crawler" / "wind_events_crawler.json"


def test_placeholder_artifact_shape_is_explicit_and_versioned():
    models_module = _reload_module("wind_events_crawler.models")
    result_repository_module = _reload_module("wind_events_crawler.result_repository")

    artifact = result_repository_module.build_placeholder_artifact(pi_id="pi-test")

    assert isinstance(artifact, models_module.ResultArtifact)
    assert artifact.schema_version == "0.1.0"
    assert artifact.generated_at_utc is None
    assert artifact.findings == []
    assert artifact.producer["pi_id"] == "pi-test"
    assert artifact.producer["worker"] == "wind_events_crawler"


def test_worker_modules_import_without_runtime_side_effects(monkeypatch: pytest.MonkeyPatch):
    import requests
    import subprocess

    def fail_request(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("network access at import time is not allowed")

    def fail_subprocess(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("git/subprocess access at import time is not allowed")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_request)
    monkeypatch.setattr(subprocess, "check_output", fail_subprocess)

    required_modules = [
        "wind_events_crawler",
        "wind_events_crawler.cli",
        "wind_events_crawler.config",
        "wind_events_crawler.exceptions",
        "wind_events_crawler.models",
        "wind_events_crawler.telemetry",
        "wind_events_crawler.locking",
        "wind_events_crawler.updater",
        "wind_events_crawler.api_client",
        "wind_events_crawler.scenario_runner",
        "wind_events_crawler.result_repository",
        "wind_events_crawler.merge_logic",
        "wind_events_crawler.run_worker",
    ]

    for module_name in required_modules:
        imported = _reload_module(module_name)
        assert imported is not None
