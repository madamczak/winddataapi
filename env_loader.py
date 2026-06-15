from __future__ import annotations

import os
from pathlib import Path


def load_repo_env(env_path: Path | None = None, *, override: bool = False) -> None:
    """Load simple KEY=VALUE pairs from the repository .env file into os.environ."""

    resolved_path = env_path or Path(__file__).resolve().parent / ".env"
    if not resolved_path.exists():
        return

    for raw_line in resolved_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
