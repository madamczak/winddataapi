"""
bins.py — Operating condition binning (mirrors degradation_crawler/bins.py).

Kept as a standalone copy so service_crawler has no cross-package imports.
"""

from __future__ import annotations

import bisect

from .config import AMBIENT_BINS, POWER_BINS, WIND_BINS


def _bin_label(value: float, edges: list[float]) -> str:
    idx = bisect.bisect_right(edges, value) - 1
    idx = max(0, min(idx, len(edges) - 2))
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
    """Return composite operating condition bin key, e.g. '(8-10, 1500-2000, 10-20)'."""
    w = _bin_label(wind,    WIND_BINS)
    p = _bin_label(power,   POWER_BINS)
    a = _bin_label(ambient, AMBIENT_BINS)
    return f"({w}, {p}, {a})"

