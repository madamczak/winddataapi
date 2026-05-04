#!/usr/bin/env python3
"""
crawl.py — API Crawler for wind farm interesting-event discovery.

Randomly samples (date, hour) pairs from a farm's data range, checks whether
ALL turbines satisfy a named pattern for that hour, and saves matches to a
JSONL file.  Multiple instances can run concurrently against the same output
file — each write is a single atomic line append.

Usage examples
--------------
  # Local API, kelmarsh, high-wind full-spin, 500 random samples
  python crawl.py --api http://localhost:8000 --farm kelmarsh \\
                  --pattern high_wind_full_spin --iterations 500

  # Remote API, farm stopped, 2 000 samples, 0.2 s between requests
  python crawl.py --api https://your-api.onrender.com --farm kelmarsh \\
                  --pattern farm_stopped --iterations 2000 --delay 0.2

  # Show all available patterns
  python crawl.py --list-patterns

  # Write matches to a custom file
  python crawl.py --api http://localhost:8000 --farm kelmarsh \\
                  --pattern rated_power --output results/rated_power.jsonl
"""

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

# ── resolve patterns module whether run as script or module ──────────────────
sys.path.insert(0, str(Path(__file__).parent))
from patterns import PATTERNS

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("apicrawler")


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str, params: dict = None,
         timeout: int = 30) -> Optional[dict]:
    """GET with basic retry logic; returns None on error."""
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            log.warning(f"Request failed (attempt {attempt + 1}/3): {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


def fetch_farm_meta(session: requests.Session, api_base: str, farm: str) -> Optional[dict]:
    """Return {turbines: [...], earliest: 'YYYY-MM-DD', latest: 'YYYY-MM-DD'}."""
    farms_data = _get(session, f"{api_base}/wind-farms")
    if not farms_data:
        return None
    farm_info = next((f for f in farms_data.get("wind_farms", [])
                      if f["directory"] == farm), None)
    if not farm_info:
        log.error(f"Farm '{farm}' not found. Available: "
                  f"{[f['directory'] for f in farms_data.get('wind_farms', [])]}")
        return None

    ranges_data = _get(session, f"{api_base}/wind-farms/time-ranges")
    if not ranges_data:
        return None
    tr = next((r for r in ranges_data.get("time_ranges", [])
               if r["farm"] == farm), None)
    if not tr:
        return None

    return {
        "turbines": farm_info["turbines"],
        "earliest": tr["earliest"][:10],   # YYYY-MM-DD
        "latest":   tr["latest"][:10],
    }


def fetch_hour_data(session: requests.Session, api_base: str, farm: str,
                    turbine: str, date_str: str, hour: int,
                    columns: list[str]) -> Optional[dict]:
    """
    Fetch one turbine's data for a single hour.
    Returns {'columns': [...], 'rows': [[...], ...]} or None.
    """
    params = {
        "file_type": "data",
        "turbine": turbine,
        "hour_from": hour,
        "hour_to": hour,
    }
    for col in columns:
        params.setdefault("columns", [])
        params["columns"].append(col)  # requests will repeat the key

    # requests handles list params as repeated keys when passed as a list
    url = f"{api_base}/wind-farms/{farm}/data/{date_str}"

    # Build params carefully: repeat 'columns' key for each column
    param_list = [
        ("file_type", "data"),
        ("turbine", turbine),
        ("hour_from", str(hour)),
        ("hour_to", str(hour)),
    ]
    for col in columns:
        param_list.append(("columns", col))

    for attempt in range(3):
        try:
            r = session.get(url, params=param_list, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            log.warning(f"Data fetch failed (attempt {attempt + 1}/3) "
                        f"{turbine} {date_str} h{hour}: {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Statistics helpers
# ─────────────────────────────────────────────────────────────────────────────

def _col_values(data: dict, col_name: str) -> list[float]:
    """Extract numeric values for a column from an API response."""
    columns = data.get("columns", [])
    rows    = data.get("rows", [])
    if col_name not in columns:
        return []
    ci = columns.index(col_name)
    vals = []
    for row in rows:
        v = row[ci] if ci < len(row) else None
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    return vals


def _mean(vals: list[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _std(vals: list[float]) -> Optional[float]:
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    variance = sum((v - m) ** 2 for v in vals) / len(vals)
    return math.sqrt(variance)


def compute_stat(vals: list[float], agg: str) -> Optional[float]:
    if agg == "mean":
        return _mean(vals)
    if agg == "std":
        return _std(vals)
    raise ValueError(f"Unknown agg: {agg!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Pattern evaluation
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_column(data: dict, criterion: dict) -> tuple[Optional[str], list[float]]:
    """
    Resolve which column to use for a criterion.

    Supports two forms:
      - Plain:     criterion["column"] → use that column directly
      - Candidate: criterion["column_candidates"] + optional "physical_range"
                   → try each candidate; pick the first whose mean falls within
                   physical_range. Falls back to the first candidate if none match.

    Returns (resolved_col_name, values_list).
    """
    if "column" in criterion:
        col  = criterion["column"]
        vals = _col_values(data, col)
        return col, vals

    candidates = criterion.get("column_candidates", [])
    phys_lo, phys_hi = (criterion.get("physical_range") or [None, None])[:2]

    best_col, best_vals = None, []
    for col in candidates:
        vals = _col_values(data, col)
        if not vals:
            continue
        if best_col is None:
            best_col, best_vals = col, vals   # keep as fallback
        if phys_lo is not None or phys_hi is not None:
            m = sum(vals) / len(vals)
            lo_ok = (phys_lo is None) or (m >= phys_lo)
            hi_ok = (phys_hi is None) or (m <= phys_hi)
            if lo_ok and hi_ok:
                return col, vals             # found a match in physical range

    return best_col, best_vals             # fallback


def evaluate_pattern(data: dict, pattern: dict) -> tuple[bool, dict]:
    """
    Check whether a turbine's hour data satisfies all criteria.

    Returns (passed: bool, details: dict) where details maps
    'column|agg' → computed value, and optionally 'column_used' for
    candidate-based criteria.
    """
    rows = data.get("rows", [])
    if len(rows) < pattern.get("min_rows", 1):
        return False, {"reason": f"only {len(rows)} rows < min {pattern.get('min_rows', 1)}"}

    details = {}
    for criterion in pattern["criteria"]:
        agg = criterion["agg"]
        lo  = criterion.get("min")
        hi  = criterion.get("max")

        resolved_col, vals = _resolve_column(data, criterion)

        if resolved_col is None or not vals:
            label = criterion.get("column") or str(criterion.get("column_candidates"))
            return False, {**details, "reason": f"no values for '{label}'"}

        value = compute_stat(vals, agg)
        if value is None:
            return False, {**details, "reason": f"could not compute {agg} for '{resolved_col}'"}

        key = f"{resolved_col}|{agg}"
        details[key] = round(value, 4)

        if lo is not None and value < lo:
            return False, {**details, "reason": f"{key}={value:.3f} < min {lo}"}
        if hi is not None and value > hi:
            return False, {**details, "reason": f"{key}={value:.3f} > max {hi}"}

    return True, details


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────

def save_match(output_path: Path, record: dict) -> None:
    """Append one match as a JSONL line (thread/process safe via line-level append)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main crawl loop
# ─────────────────────────────────────────────────────────────────────────────

def crawl(
    api_base: str,
    farm: str,
    pattern_name: str,
    iterations: int,
    output_path: Path,
    delay: float,
    turbine_delay: float,
    seed: Optional[int],
    turbines_filter: Optional[list[str]],
) -> None:
    if pattern_name not in PATTERNS:
        log.error(f"Unknown pattern '{pattern_name}'. "
                  f"Available: {list(PATTERNS.keys())}")
        sys.exit(1)

    pattern = PATTERNS[pattern_name]
    log.info(f"Pattern : {pattern_name}")
    log.info(f"Desc    : {pattern['description']}")
    log.info(f"Farm    : {farm}")
    log.info(f"API     : {api_base}")
    log.info(f"Output  : {output_path}")
    log.info(f"Samples : {iterations}")
    log.info(f"Delay   : {delay} s between slots / {turbine_delay} s between turbine checks")

    if seed is not None:
        random.seed(seed)

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    # ── Bootstrap: get farm metadata ─────────────────────────────────────────
    log.info("Fetching farm metadata…")
    meta = fetch_farm_meta(session, api_base, farm)
    if not meta:
        log.error("Could not fetch farm metadata — aborting.")
        sys.exit(1)

    turbines = meta["turbines"]
    if turbines_filter:
        turbines = [t for t in turbines if t in turbines_filter]
        if not turbines:
            log.error(f"None of the requested turbines {turbines_filter} are in this farm.")
            sys.exit(1)
    earliest = date.fromisoformat(meta["earliest"])
    latest   = date.fromisoformat(meta["latest"])
    total_days = (latest - earliest).days

    log.info(f"Turbines: {turbines}")
    log.info(f"Range   : {earliest} → {latest} ({total_days} days)")

    columns   = pattern["columns"]
    checked   = 0
    matches   = 0
    skipped   = 0

    # ── Sampling loop ─────────────────────────────────────────────────────────
    for i in range(1, iterations + 1):
        # Pick a random date and hour
        offset   = random.randint(0, total_days)
        sample_d = earliest + timedelta(days=offset)
        sample_h = random.randint(0, 23)
        date_str = sample_d.isoformat()

        checked += 1
        log.info(f"[{i:>{len(str(iterations))}}/{iterations}]  "
                 f"{date_str} h{sample_h:02d}  — checking {turbines[0]} first…")

        # ── Check first turbine ───────────────────────────────────────────────
        first_data = fetch_hour_data(
            session, api_base, farm, turbines[0], date_str, sample_h, columns)

        if first_data is None:
            log.warning(f"  ✗ API error for {turbines[0]} — skipping slot")
            skipped += 1
            if delay:
                time.sleep(delay)          # slot delay — wait before next random slot
            continue

        passed, details = evaluate_pattern(first_data, pattern)
        if not passed:
            reason = details.pop("reason", "—")
            log.debug(f"  ✗ {turbines[0]} failed: {reason}")
            if delay:
                time.sleep(delay)          # slot delay — first turbine failed, move on
            continue

        log.info(f"  ✓ {turbines[0]} matches — checking remaining {len(turbines)-1} turbines…")

        # ── Check all remaining turbines ──────────────────────────────────────
        all_turbine_details: dict[str, dict] = {turbines[0]: details}
        all_passed = True

        for turbine in turbines[1:]:
            if turbine_delay:
                time.sleep(turbine_delay)  # short delay — within a promising slot
            t_data = fetch_hour_data(
                session, api_base, farm, turbine, date_str, sample_h, columns)

            if t_data is None:
                log.warning(f"  ✗ API error for {turbine} — aborting slot")
                all_passed = False
                break

            t_passed, t_details = evaluate_pattern(t_data, pattern)
            if not t_passed:
                reason = t_details.pop("reason", "—")
                log.info(f"  ✗ {turbine} failed: {reason}")
                all_passed = False
                break

            log.info(f"  ✓ {turbine} matches")
            all_turbine_details[turbine] = t_details

        if not all_passed:
            if delay:
                time.sleep(delay)          # slot delay — partial match, move on
            continue

        # ── All turbines match! ───────────────────────────────────────────────
        matches += 1
        record = {
            "pattern":          pattern_name,
            "farm":             farm,
            "date":             date_str,
            "hour":             sample_h,
            "turbines_matched": turbines,
            "details_by_turbine": all_turbine_details,
            "timestamp_utc":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_match(output_path, record)
        log.info(
            f"  🎯 MATCH #{matches}  →  {date_str} h{sample_h:02d}  "
            f"(saved to {output_path})"
        )

        if delay:
            time.sleep(delay)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("─" * 60)
    log.info(f"Done.  Checked={checked}  Matches={matches}  Skipped(errors)={skipped}")
    if output_path.exists():
        log.info(f"Results written to: {output_path.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--api",
        default=os.environ.get("WINDDATA_API", "http://localhost:8000"),
        metavar="URL",
        help="Base URL of the Wind Data API "
             "(default: $WINDDATA_API or http://localhost:8000)",
    )
    p.add_argument(
        "--farm",
        default="kelmarsh",
        help="Farm directory name, e.g. kelmarsh or penmanshiel (default: kelmarsh)",
    )
    p.add_argument(
        "--pattern",
        default="high_wind_full_spin",
        help=f"Pattern name (default: high_wind_full_spin). "
             f"Use --list-patterns to see all.",
    )
    p.add_argument(
        "--iterations",
        type=int,
        default=500,
        metavar="N",
        help="Number of random (date, hour) samples to check (default: 500)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="Output JSONL file path. Defaults to results/<farm>_<pattern>.jsonl",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=180.0,
        metavar="SECONDS",
        help="Seconds to sleep between slots (after first turbine check). Default: 180 (3 min).",
    )
    p.add_argument(
        "--turbine-delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        dest="turbine_delay",
        help="Seconds to sleep between turbine checks within a promising slot "
             "(only triggered when the first turbine matches). Default: 1.",
    )
    p.add_argument(
        "--turbines",
        nargs="+",
        metavar="TURBINE",
        default=None,
        help="Restrict check to specific turbines, e.g. --turbines turbine_2 turbine_3. "
             "Useful when some turbines have inconsistent SCADA column labelling.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="INT",
        help="Random seed for reproducible sampling (default: random)",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging (shows every rejection reason)",
    )
    p.add_argument(
        "--list-patterns",
        action="store_true",
        help="Print all available patterns and exit",
    )
    return p


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.list_patterns:
        print("\nAvailable patterns:\n")
        for name, pat in PATTERNS.items():
            print(f"  {name}")
            print(f"    {pat['description']}")
            print(f"    Criteria:")
            for c in pat["criteria"]:
                parts = [f"column={c['column']!r}", f"agg={c['agg']}"]
                if c.get("min") is not None:
                    parts.append(f"min={c['min']}")
                if c.get("max") is not None:
                    parts.append(f"max={c['max']}")
                print(f"      • {',  '.join(parts)}")
            print()
        sys.exit(0)

    output = args.output or Path(__file__).parent / "results" / f"{args.farm}_{args.pattern}.jsonl"

    crawl(
        api_base        = args.api.rstrip("/"),
        farm            = args.farm,
        pattern_name    = args.pattern,
        iterations      = args.iterations,
        output_path     = output,
        delay           = args.delay,
        turbine_delay   = args.turbine_delay,
        seed            = args.seed,
        turbines_filter = args.turbines,
    )


if __name__ == "__main__":
    main()

