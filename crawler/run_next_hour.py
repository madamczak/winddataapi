#!/usr/bin/env python3
"""
run_next_hour.py — Collect exactly one missing hour then exit.

Designed to be called by cron with flock so only one instance runs at a time:

    */5 * * * * flock -n /tmp/wind_crawler.lock \
        /usr/bin/python3 /home/pi/Programming/winddataAPI/crawler/run_next_hour.py \
        --farm kelmarsh --turbine turbine_2 \
        --start "2016-05-30 20:00:00" --end "2023-05-30 22:59:59" \
        --no-weather >> /home/pi/crawler.log 2>&1

Exit codes:
    0  — hour collected successfully, or nothing left to do
    1  — collection failed
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iter_hours(start: datetime, end: datetime):
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        yield current
        current += timedelta(hours=1)


def hour_exists(output_dir: Path, farm: str, turbine: str, hour: datetime) -> bool:
    fname = hour.strftime("%Y-%m-%d_%H") + "_raw.json"
    return (output_dir / farm / turbine / fname).exists()


def find_next_missing(
    output_dir: Path,
    farm: str,
    turbine: str,
    start: datetime,
    end: datetime,
) -> datetime | None:
    for h in iter_hours(start, end):
        if not hour_exists(output_dir, farm, turbine, h):
            return h
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect the next missing hour and exit — safe for cron.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--farm",    required=True, help="Farm name, e.g. kelmarsh")
    parser.add_argument("--turbine", required=True, help="Turbine name, e.g. turbine_2")
    parser.add_argument("--start",   required=True, metavar="DATETIME",
                        help='Range start, e.g. "2016-05-30 20:00:00"')
    parser.add_argument("--end",     required=True, metavar="DATETIME",
                        help='Range end,   e.g. "2023-05-30 22:59:59"')
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--no-weather", action="store_true")
    parser.add_argument("--columns",    default=None,
                        help="Path to columns config (passed to collect_hourly.py)")
    args = parser.parse_args()

    start_dt   = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    end_dt     = datetime.strptime(args.end,   "%Y-%m-%d %H:%M:%S")
    output_dir = Path(args.output_dir)

    # Count progress for informational output
    all_hours   = list(iter_hours(start_dt, end_dt))
    done        = sum(1 for h in all_hours
                      if hour_exists(output_dir, args.farm, args.turbine, h))
    total       = len(all_hours)

    next_hour = find_next_missing(output_dir, args.farm, args.turbine, start_dt, end_dt)

    if next_hour is None:
        print(f"[run_next_hour] All {total} hours already collected. Nothing to do.")
        return 0

    remaining = total - done
    print(
        f"[run_next_hour] Progress: {done}/{total} done, {remaining} remaining. "
        f"Next: {next_hour.strftime('%Y-%m-%d %H:00')}"
    )

    h_start = next_hour.strftime("%Y-%m-%d %H:%M:%S")
    h_end   = (next_hour + timedelta(hours=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "collect_hourly.py"),
        "--farm",       args.farm,
        "--turbine",    args.turbine,
        "--start",      h_start,
        "--end",        h_end,
        "--output-dir", args.output_dir,
    ]
    if args.no_weather:
        cmd.append("--no-weather")
    if args.columns:
        cmd.extend(["--columns", args.columns])

    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode not in (0, 2):
        print(f"[run_next_hour] collect_hourly.py exited with code {result.returncode}")
        return 1

    # Print updated progress after collection
    done_after = sum(1 for h in all_hours
                     if hour_exists(output_dir, args.farm, args.turbine, h))
    remaining_after = total - done_after
    print(
        f"[run_next_hour] Done. Progress: {done_after}/{total}. "
        f"{remaining_after} hour(s) still to go."
    )
    if remaining_after == 0:
        print("[run_next_hour] All hours collected! You can remove the cron entry.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

