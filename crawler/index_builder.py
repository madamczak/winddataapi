"""
index_builder.py — builds a wind speed index over all collected summary files.

Scans every *_summary.json in the output directory, reads the mean wind speed,
and writes output/wind_speed_index.json grouping file paths by 0.5 m/s bins
covering 0–30 m/s.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BIN_STEP = 0.5
BIN_MAX = 30.0
WIND_FIELD = "Wind speed (m/s)"


def build_index(output_dir: str = "output") -> Path:
    """
    Scan all *_summary.json files under *output_dir*, group them by mean
    wind speed bin and write wind_speed_index.json.

    Returns the path to the written index file.
    """
    root = Path(output_dir)

    # Initialise all bins as empty lists
    bins: dict[str, list[str]] = {}
    low = 0.0
    while round(low, 1) < BIN_MAX:
        high = round(low + BIN_STEP, 1)
        key = f"{low:.1f}-{high:.1f}"
        bins[key] = []
        low = high

    # Also a bucket for anything above BIN_MAX or that couldn't be read
    bins[f"{BIN_MAX:.1f}+"] = []
    bins["unknown"] = []

    summary_files = sorted(root.rglob("*_summary.json"))
    if not summary_files:
        logger.warning("No summary files found under %s", root)

    for path in summary_files:
        rel = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            wind_entry = data.get("stats", {}).get(WIND_FIELD)
            if wind_entry is None:
                bins["unknown"].append(rel)
                continue
            mean_ws = float(wind_entry["mean"])
        except Exception as exc:
            logger.warning("Could not read %s: %s", rel, exc)
            bins["unknown"].append(rel)
            continue

        if mean_ws >= BIN_MAX:
            bins[f"{BIN_MAX:.1f}+"].append(rel)
        elif mean_ws < 0:
            bins["unknown"].append(rel)
        else:
            bin_idx = int(mean_ws / BIN_STEP)
            low = round(bin_idx * BIN_STEP, 1)
            high = round(low + BIN_STEP, 1)
            key = f"{low:.1f}-{high:.1f}"
            bins[key].append(rel)

    # Drop empty bins to keep the file readable
    bins = {k: v for k, v in bins.items() if v}

    index_path = root / "wind_speed_index.json"
    index_path.write_text(
        json.dumps(
            {
                "_meta": {
                    "description": "Groups summary file paths by mean wind speed bin (m/s)",
                    "bin_step_ms": BIN_STEP,
                    "wind_field": WIND_FIELD,
                    "total_files": sum(len(v) for v in bins.values()),
                },
                "bins": bins,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(
        "Wind speed index written → %s  (%d files, %d non-empty bins)",
        index_path,
        sum(len(v) for v in bins.values()),
        len(bins) - 1,  # exclude _meta
    )
    return index_path

