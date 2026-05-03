#!/usr/bin/env python3
"""
start_and_crawl.py — Start the FastAPI server and crawl all missing hours.

Usage:
    python start_and_crawl.py [options]

Options are forwarded to run_next_hour.py (farm, turbine, start, end, etc.).
The API is started on localhost:8000 and shut down when crawling is complete.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

API_HOST = "0.0.0.0"
API_PORT = 8000
API_URL  = f"http://127.0.0.1:{API_PORT}"

ROOT_DIR    = Path(__file__).parent
CRAWLER_DIR = ROOT_DIR / "crawler"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_api(timeout: int = 30) -> bool:
    """Return True when the API is responding, False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{API_URL}/docs", timeout=2)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def iter_hours(start: datetime, end: datetime):
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        yield current
        current += timedelta(hours=1)


def iter_hours_cross_year(start: datetime, end: datetime):
    """Yield hours ordered by (month, day, hour_of_day, year).

    The same clock-hour on the same calendar day is collected across ALL years
    before moving on to the next hour slot — ideal for year-over-year comparison.
    """
    all_hours = list(iter_hours(start, end))
    all_hours.sort(key=lambda h: (h.month, h.day, h.hour, h.year))
    return all_hours


def hour_exists(output_dir: Path, farm: str, turbine: str, hour: datetime) -> bool:
    fname = hour.strftime("%Y-%m-%d_%H") + "_raw.json"
    return (output_dir / farm / turbine / fname).exists()


def count_done(output_dir: Path, farm: str, turbine: str, start: datetime, end: datetime) -> int:
    return sum(1 for h in iter_hours(start, end)
               if hour_exists(output_dir, farm, turbine, h))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the API and crawl all missing hours.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--farm",       default="kelmarsh",    help="Farm name (default: kelmarsh)")
    parser.add_argument("--turbine",    default="turbine_2",   help="Turbine name (default: turbine_2)")
    parser.add_argument("--start",      default="2016-06-08 00:00:00", metavar="DATETIME",
                        help='Range start (default: "2016-06-08 00:00:00")')
    parser.add_argument("--end",        default="2023-12-31 23:59:59", metavar="DATETIME",
                        help='Range end   (default: "2023-12-31 23:59:59")')
    parser.add_argument("--output-dir", default=str(CRAWLER_DIR / "output"),
                        help="Output directory for collected files")
    parser.add_argument("--no-weather", action="store_true",
                        help="Skip weather data collection")
    parser.add_argument("--columns",    default=None,
                        help="Path to columns config JSON")
    parser.add_argument("--api-timeout", type=int, default=30,
                        help="Seconds to wait for API to become ready (default: 30)")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    end_dt   = datetime.strptime(args.end,   "%Y-%m-%d %H:%M:%S")
    output_dir = Path(args.output_dir)


    # -----------------------------------------------------------------------
    # 1. Start API
    # -----------------------------------------------------------------------
    print(f"[start_and_crawl] Starting API on {API_HOST}:{API_PORT} ...")
    api_proc = subprocess.Popen(
        [sys.executable, str(ROOT_DIR / "main.py"), str(API_PORT)],
        cwd=ROOT_DIR,
    )

    if not wait_for_api(args.api_timeout):
        print("[start_and_crawl] ERROR: API did not start in time. Aborting.")
        api_proc.terminate()
        return 1

    print(f"[start_and_crawl] API is ready at {API_URL}")

    # -----------------------------------------------------------------------
    # 2. Crawl all missing hours in cross-year order
    # -----------------------------------------------------------------------
    ordered_hours = iter_hours_cross_year(start_dt, end_dt)
    total = len(ordered_hours)
    done  = 0

    print(f"[start_and_crawl] Crawling {args.farm}/{args.turbine} "
          f"from {args.start} to {args.end} — {total} hours total (cross-year order).")

    try:
        for hour in ordered_hours:
            if hour_exists(output_dir, args.farm, args.turbine, hour):
                done += 1
                continue

            h_start = hour.strftime("%Y-%m-%d %H:%M:%S")
            h_end   = (hour + timedelta(hours=1) - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
            remaining = total - done
            print(f"[start_and_crawl] [{done}/{total}] Collecting {h_start}  ({remaining} remaining) ...")

            cmd = [
                sys.executable,
                str(CRAWLER_DIR / "collect_hourly.py"),
                "--farm",       args.farm,
                "--turbine",    args.turbine,
                "--start",      h_start,
                "--end",        h_end,
                "--output-dir", str(output_dir),
            ]
            if args.no_weather:
                cmd.append("--no-weather")
            if args.columns:
                cmd.extend(["--columns", args.columns])

            result = subprocess.run(cmd, cwd=CRAWLER_DIR)

            if result.returncode not in (0, 2):
                print(f"[start_and_crawl] collect_hourly.py exited with code {result.returncode}. "
                      f"Skipping and continuing ...")
            else:
                done += 1

        print(f"[start_and_crawl] All {total} hours collected. Done!")

    except KeyboardInterrupt:
        print(f"\n[start_and_crawl] Interrupted. Progress: {done}/{total} hours collected.")

    finally:
        # -----------------------------------------------------------------------
        # 3. Shut down API
        # -----------------------------------------------------------------------
        print("[start_and_crawl] Shutting down API ...")
        api_proc.terminate()
        try:
            api_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        print("[start_and_crawl] API stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

