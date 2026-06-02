"""
trend_analysis.py — OLS temporal trend fitting per operating condition bin.

For each (turbine, bin, col) combination, loads all observations accumulated
by accumulate.py and fits a linear regression:

    temperature = slope × ordinal_day + intercept

The slope_per_year (= slope × 365) in °C/year is the degradation signal.
A sustained upward trend in a given operating condition is strong evidence
of component degradation — insulated from seasonal and load effects because
the operating condition bin already controls for wind, power, and ambient.

Usage:
    from degradation_crawler.trend_analysis import analyse_turbine
    results = analyse_turbine("kelmarsh", "turbine_2")
    for r in results:
        if r.severity != "OK":
            print(r)
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config import (
    TEMP_COLS,
    TREND_CRITICAL_SLOPE,
    TREND_DB,
    TREND_MIN_DAY_SPAN,
    TREND_MIN_OBS,
    TREND_MIN_YEARS,
    TREND_WARNING_SLOPE,
    TREND_WATCH_SLOPE,
)
from .machine_logger import log


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TrendResult:
    """
    OLS fit result for one turbine / operating condition bin / temperature column.

    Written to trend_results table in trend_observations.db.
    """
    farm:            str
    turbine:         str
    bin:             str
    col:             str
    slope_per_year:  float    # °C / year (positive = heating up over time)
    intercept:       float
    r2:              float
    n_obs:           int
    day_span:        int      # max_ordinal − min_ordinal
    years_covered:   int      # number of distinct calendar years with data
    t_stat:          float
    p_value_proxy:   Optional[float]   # None if scipy unavailable
    severity:        str      # OK / WATCH / WARNING / CRITICAL
    analysed_at:     str      # UTC ISO

    def to_dict(self) -> dict:
        return {
            "farm":           self.farm,
            "turbine":        self.turbine,
            "bin":            self.bin,
            "col":            self.col,
            "slope_per_year": round(self.slope_per_year, 4),
            "intercept":      round(self.intercept, 4),
            "r2":             round(self.r2, 4),
            "n_obs":          self.n_obs,
            "day_span":       self.day_span,
            "years_covered":  self.years_covered,
            "t_stat":         round(self.t_stat, 3),
            "p_value_proxy":  (
                round(self.p_value_proxy, 4)
                if self.p_value_proxy is not None else None
            ),
            "severity":       self.severity,
            "analysed_at":    self.analysed_at,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_turbine(
    farm: str,
    turbine: str,
    db_path=TREND_DB,
) -> list[TrendResult]:
    """
    Load all observations for a turbine, fit OLS per (bin, col),
    classify severity, persist results.

    Returns all TrendResult objects (including severity=OK).
    """
    if not db_path.exists():
        log("WARN", "trend_no_db", farm=farm, turbine=turbine,
            note="trend_observations.db not found — run accumulate first.")
        return []

    conn = sqlite3.connect(db_path)
    results = _fit_all(conn, farm, turbine)
    if results:
        _write_trend_results(results, conn)
    conn.close()

    counts = {s: sum(1 for r in results if r.severity == s)
              for s in ("OK", "WATCH", "WARNING", "CRITICAL")}
    log("INFO", "trend_analysis_done", farm=farm, turbine=turbine,
        bins_analysed=len(results), **counts)
    return results


def load_trend_results(
    farm: str,
    turbine: Optional[str] = None,
    severity_filter: Optional[list[str]] = None,
    db_path=TREND_DB,
) -> list[dict]:
    """
    Load persisted trend results from the DB.

    severity_filter: e.g. ["WATCH","WARNING","CRITICAL"] to exclude OK rows.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        q = "SELECT * FROM trend_results WHERE farm=?"
        args: list = [farm]
        if turbine:
            q += " AND turbine=?"
            args.append(turbine)
        if severity_filter:
            placeholders = ",".join("?" * len(severity_filter))
            q += f" AND severity IN ({placeholders})"
            args.extend(severity_filter)
        q += " ORDER BY turbine, col, slope_per_year DESC"
        rows = conn.execute(q, args).fetchall()
        cols = [d[0] for d in conn.execute(q + " LIMIT 0", args).description
                ] if not rows else [
            "farm","turbine","bin","col","slope_per_year","intercept",
            "r2","n_obs","day_span","years_covered","t_stat","p_value_proxy",
            "severity","analysed_at"
        ]
        return [dict(zip(cols, r)) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internal: fitting
# ---------------------------------------------------------------------------

def _fit_all(
    conn: sqlite3.Connection,
    farm: str,
    turbine: str,
) -> list[TrendResult]:
    """Fetch all (bin, col) pairs and fit OLS for each."""
    try:
        pairs = conn.execute(
            "SELECT DISTINCT bin, col FROM observations WHERE farm=? AND turbine=?",
            (farm, turbine),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    results = []
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for (bin_key, col) in pairs:
        if col not in TEMP_COLS:
            continue

        rows_data = conn.execute(
            """SELECT ordinal_day, value, date
               FROM observations
               WHERE farm=? AND turbine=? AND bin=? AND col=?
               ORDER BY ordinal_day""",
            (farm, turbine, bin_key, col),
        ).fetchall()

        if len(rows_data) < TREND_MIN_OBS:
            continue

        xs = [r[0] for r in rows_data]
        ys = [r[1] for r in rows_data]
        day_span = xs[-1] - xs[0]

        if day_span < TREND_MIN_DAY_SPAN:
            continue

        # Require observations from at least TREND_MIN_YEARS distinct calendar years
        # This prevents single-year seasonal temperature cycles from masquerading
        # as multi-year degradation trends.
        years = {r[2][:4] for r in rows_data if r[2]}  # set of "YYYY" strings
        if len(years) < TREND_MIN_YEARS:
            continue

        slope, intercept, r2, t_stat, p_val = _ols(xs, ys)
        slope_per_year = slope * 365.0
        severity = _classify_severity(slope_per_year)

        results.append(TrendResult(
            farm=farm,
            turbine=turbine,
            bin=bin_key,
            col=col,
            slope_per_year=slope_per_year,
            intercept=intercept,
            r2=r2,
            n_obs=len(xs),
            day_span=day_span,
            years_covered=len(years),
            t_stat=t_stat,
            p_value_proxy=p_val,
            severity=severity,
            analysed_at=now_utc,
        ))

    return results


def _ols(
    xs: list[float],
    ys: list[float],
) -> tuple[float, float, float, float, Optional[float]]:
    """
    Pure-Python OLS: returns (slope, intercept, r2, t_stat, p_value_proxy).

    xs = ordinal_day values (the independent variable, time)
    ys = temperature values (the dependent variable)

    p_value_proxy uses scipy.special.betainc if available, else None.
    """
    n = len(xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n

    ss_xx = sum((x - xbar) ** 2 for x in xs)
    ss_xy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))

    if ss_xx == 0:
        return 0.0, ybar, 0.0, 0.0, None

    slope     = ss_xy / ss_xx
    intercept = ybar - slope * xbar

    # R²
    y_pred   = [slope * x + intercept for x in xs]
    ss_res   = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
    ss_tot   = sum((y - ybar) ** 2 for y in ys)
    r2       = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Standard error of slope, t-statistic
    ms_res   = ss_res / (n - 2) if n > 2 else 0.0
    se_slope = math.sqrt(ms_res / ss_xx) if ms_res > 0 and ss_xx > 0 else 0.0
    t_stat   = slope / se_slope if se_slope > 0 else 0.0

    # p-value (two-tailed) via scipy if available
    p_val: Optional[float] = None
    try:
        from scipy.stats import t as t_dist       # type: ignore[import]
        p_val = float(2 * t_dist.sf(abs(t_stat), df=n - 2))
    except ImportError:
        pass

    return slope, intercept, r2, t_stat, p_val


def _classify_severity(slope_per_year: float) -> str:
    """Map °C/year slope to severity label."""
    abs_slope = abs(slope_per_year)
    if abs_slope >= TREND_CRITICAL_SLOPE:
        return "CRITICAL"
    if abs_slope >= TREND_WARNING_SLOPE:
        return "WARNING"
    if abs_slope >= TREND_WATCH_SLOPE:
        return "WATCH"
    return "OK"


# ---------------------------------------------------------------------------
# Internal: persistence
# ---------------------------------------------------------------------------

def _write_trend_results(
    results: list[TrendResult],
    conn: sqlite3.Connection,
) -> int:
    """Upsert all TrendResult objects into the trend_results table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trend_results (
            farm            TEXT NOT NULL,
            turbine         TEXT NOT NULL,
            bin             TEXT NOT NULL,
            col             TEXT NOT NULL,
            slope_per_year  REAL,
            intercept       REAL,
            r2              REAL,
            n_obs           INTEGER,
            day_span        INTEGER,
            years_covered   INTEGER,
            t_stat          REAL,
            p_value_proxy   REAL,
            severity        TEXT,
            analysed_at     TEXT,
            PRIMARY KEY (farm, turbine, bin, col)
        )
    """)
    conn.executemany(
        """INSERT OR REPLACE INTO trend_results
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (r.farm, r.turbine, r.bin, r.col,
             r.slope_per_year, r.intercept, r.r2,
             r.n_obs, r.day_span, r.years_covered,
             r.t_stat, r.p_value_proxy,
             r.severity, r.analysed_at)
            for r in results
        ],
    )
    conn.commit()
    return len(results)


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def print_trend_summary(results: list[TrendResult | dict]) -> None:
    """
    Print a compact severity-sorted table to stdout.

    Accepts both TrendResult objects and dicts (from load_trend_results).
    """
    SEV_ORDER = {"CRITICAL": 0, "WARNING": 1, "WATCH": 2, "OK": 3}

    def _g(r, k):
        return r[k] if isinstance(r, dict) else getattr(r, k)

    flagged = [r for r in results if _g(r, "severity") != "OK"]
    if not flagged:
        print("No degradation trends detected above WATCH threshold.")
        return

    flagged.sort(key=lambda r: (SEV_ORDER.get(_g(r, "severity"), 9),
                                 -abs(_g(r, "slope_per_year"))))

    hdr = (f"{'Turbine':<12} {'Bin':<30} {'Sensor':<45} {'Severity':<10} "
           f"{'Slope °C/yr':>11} {'n_obs':>6} {'yrs':>4} {'R²':>6} {'span_days':>9}")
    print(hdr)
    print("-" * len(hdr))
    for r in flagged:
        print(
            f"{_g(r,'turbine'):<12} "
            f"{_g(r,'bin'):<30} "
            f"{_g(r,'col'):<45} "
            f"{_g(r,'severity'):<10} "
            f"{_g(r,'slope_per_year'):>+11.3f} "
            f"{_g(r,'n_obs'):>6} "
            f"{_g(r,'years_covered'):>4} "
            f"{_g(r,'r2'):>6.3f} "
            f"{_g(r,'day_span'):>9}"
        )

