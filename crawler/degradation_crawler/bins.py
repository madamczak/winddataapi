"""
bins.py — Operating condition binning helpers.

Maps a (wind_speed, power, ambient_temp) triple to a discrete bin key used as
the dict key in the baseline store and as the op_bin field in residuals JSONL.

The bin key is a human-readable string, e.g. "(8-10, 1500-2000, 10-20)"
so it is meaningful when stored in SQLite and in log lines.
"""

from __future__ import annotations

import bisect

from .config import WIND_BINS, POWER_BINS, AMBIENT_BINS


def _bin_label(value: float, edges: list[float]) -> str:
    """
    Return a human-readable label for which bin *value* falls in.

    Examples (with WIND_BINS = [0, 4, 6, 8, 10, 12, inf]):
        3.5  → "0-4"
        7.2  → "6-8"
        15.0 → "12+"
    """
    idx = bisect.bisect_right(edges, value) - 1
    idx = max(0, min(idx, len(edges) - 2))  # clamp to valid range

    lo = edges[idx]
    hi = edges[idx + 1]

    lo_str = str(int(lo)) if lo != float("-inf") else "-inf"
    hi_str = str(int(hi)) if hi != float("inf") else "+"

    if hi == float("inf"):
        return f"{lo_str}+"
    if lo == float("-inf"):
        return f"<{hi_str}"
    return f"{lo_str}-{hi_str}"


def get_bin(wind: float, power: float, ambient: float) -> str:
    """
    Return the composite bin key for the given operating condition triple.

    Key format: "(wind_label, power_label, ambient_label)"
    e.g. "(8-10, 1500-2000, 10-20)"

    This O(1) key is used for:
      - Baseline dict lookup
      - Residuals JSONL "op_bin" field
      - SQLite baseline table "bin" column
    """
    w = _bin_label(wind, WIND_BINS)
    p = _bin_label(power, POWER_BINS)
    a = _bin_label(ambient, AMBIENT_BINS)
    return f"({w}, {p}, {a})"


def parse_bin(bin_key: str) -> tuple[str, str, str]:
    """
    Parse a bin key back into (wind_label, power_label, ambient_label).

    Useful for display and filtering.
    """
    inner = bin_key.strip("()")
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Invalid bin key: {bin_key!r}")
    return parts[0], parts[1], parts[2]

