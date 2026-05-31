"""
report.py — Phase D: Console summary and JSONL export of service deltas.

Prints a severity-sorted table to stdout and (optionally) appends all
ServiceDelta dicts to a JSONL file for downstream ingestion.

Usage:
    from service_crawler.report import print_delta_summary, export_jsonl
    print_delta_summary(all_deltas)
    export_jsonl(all_deltas)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .analysis import ServiceDelta
from .config import REPORT_JSONL

# Severity display order (most alarming first)
_SEV_ORDER: dict[str, int] = {
    "WORSENED":           0,
    "SLIGHT_DECLINE":     1,
    "NEUTRAL":            2,
    "SLIGHT_IMPROVEMENT": 3,
    "IMPROVED":           4,
}

# ANSI colour codes (suppressed if not a TTY)
_COLOURS: dict[str, str] = {
    "WORSENED":           "\033[91m",   # bright red
    "SLIGHT_DECLINE":     "\033[93m",   # yellow
    "NEUTRAL":            "\033[0m",    # default
    "SLIGHT_IMPROVEMENT": "\033[96m",   # cyan
    "IMPROVED":           "\033[92m",   # green
}
_RESET = "\033[0m"


def _g(r: Union[ServiceDelta, dict], k: str):
    return r[k] if isinstance(r, dict) else getattr(r, k)


def print_delta_summary(
    results: list[Union[ServiceDelta, dict]],
    show_neutral: bool = False,
    use_colour: bool = True,
) -> None:
    """
    Print a compact, severity-sorted table of service delta results.

    Parameters
    ----------
    results :
        List of ServiceDelta objects or equivalent dicts.
    show_neutral :
        If False (default), NEUTRAL rows are omitted to keep the table focused
        on noteworthy events.  Pass True to show everything.
    use_colour :
        Emit ANSI colour codes if True (default).  Set False for plain text.
    """
    if not results:
        print("No service delta results to display.")
        return

    display = results if show_neutral else [
        r for r in results if _g(r, "severity") != "NEUTRAL"
    ]

    if not display:
        print("All service events resulted in NEUTRAL delta (±1 °C).")
        return

    display.sort(key=lambda r: (
        _SEV_ORDER.get(_g(r, "severity"), 9),
        _g(r, "turbine"),
        _g(r, "event_start"),
        _g(r, "col"),
    ))

    # Group by turbine + event for cleaner output
    hdr = (
        f"{'Turbine':<12} {'Event start':<12} {'Event end':<12} "
        f"{'Bin':<30} {'Sensor':<45} "
        f"{'Severity':<20} {'Δ °C':>7} "
        f"{'μ pre':>7} {'μ post':>7} {'n_pre':>6} {'n_post':>6}"
    )
    print(hdr)
    print("-" * len(hdr))

    prev_event = None
    for r in display:
        turbine     = _g(r, "turbine")
        event_start = _g(r, "event_start")
        event_end   = _g(r, "event_end")
        bin_key     = _g(r, "bin")
        col         = _g(r, "col")
        severity    = _g(r, "severity")
        delta       = _g(r, "delta")
        mean_pre    = _g(r, "mean_pre")
        mean_post   = _g(r, "mean_post")
        n_pre       = _g(r, "n_pre")
        n_post      = _g(r, "n_post")

        # Blank separator between events
        cur_event = (turbine, event_start)
        if prev_event is not None and cur_event != prev_event:
            print()
        prev_event = cur_event

        colour = _COLOURS.get(severity, _RESET) if use_colour else ""
        reset  = _RESET if use_colour else ""

        print(
            f"{colour}"
            f"{turbine:<12} {event_start:<12} {event_end:<12} "
            f"{bin_key:<30} {col:<45} "
            f"{severity:<20} {delta:>+7.2f} "
            f"{mean_pre:>7.2f} {mean_post:>7.2f} {n_pre:>6} {n_post:>6}"
            f"{reset}"
        )


def export_jsonl(
    results: list[Union[ServiceDelta, dict]],
    path: Path = REPORT_JSONL,
) -> int:
    """
    Append all delta results to a JSONL file (one JSON object per line).

    Returns the number of lines written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "a", encoding="utf-8") as fh:
        for r in results:
            line = r.to_dict() if isinstance(r, ServiceDelta) else r
            fh.write(json.dumps(line) + "\n")
            count += 1
    return count


def print_event_summary(
    farm: str,
    turbines: list[str],
    all_events: dict[str, list[dict]],
) -> None:
    """
    Print a summary of discovered service events (before data collection).

    Parameters
    ----------
    all_events : {turbine: [event_dicts]}
    """
    total = sum(len(v) for v in all_events.values())
    print(f"\nDiscovered {total} Scheduled Maintenance event(s) "
          f"across {len(turbines)} turbine(s) for farm '{farm}':")
    for turbine in turbines:
        events = all_events.get(turbine, [])
        if not events:
            print(f"  {turbine:<14}  (no events)")
            continue
        for ev in events:
            print(
                f"  {turbine:<14}  {ev['event_start']}  →  {ev['event_end']}  "
                f"({ev['duration_days']} day(s))  id={ev['event_id']}"
            )
    print()

