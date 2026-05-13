import os
import glob
import sqlite3
from typing import List, Dict, Optional, Tuple

# DATA_DIR can be overridden by the DATA_DIR environment variable.
# Default: the data_by_turbine/ folder next to the project root.
_default = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data_by_turbine'))
BASE_DIR = os.environ.get('DATA_DIR', _default)


def discover_sites() -> Dict[str, str]:
    """Return map of site name -> sqlite file path"""
    out = {}
    for p in glob.glob(os.path.join(BASE_DIR, '*.db')):
        name = os.path.splitext(os.path.basename(p))[0]
        out[name] = p
    return out


def _connect(db_path: str):
    # read-only connection mode
    uri = f'file:{db_path}?mode=ro'
    return sqlite3.connect(uri, uri=True)


def list_turbines(site: str) -> List[str]:
    sites = discover_sites()
    if site not in sites:
        raise FileNotFoundError(f"site not found: {site}")
    con = _connect(sites[site])
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    con.close()
    return rows


def get_table_columns(site: str, table: str) -> List[Tuple[str, str]]:
    sites = discover_sites()
    if site not in sites:
        raise FileNotFoundError(f"site not found: {site}")
    con = _connect(sites[site])
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info('{table}')")
    cols = [(r[1], r[2]) for r in cur.fetchall()]
    con.close()
    return cols


def _choose_timestamp_column(cols: List[Tuple[str, str]]) -> Optional[str]:
    # pick a likely timestamp column by name
    candidates = [c[0] for c in cols]
    for key in ['Date and time', 'Timestamp start', 'Timestamp', 'Time', 'Date']:
        for c in candidates:
            if key.lower() in c.lower():
                return c
    # fallback to first column
    return candidates[0] if candidates else None


def query_rows(site: str, table: str, start: Optional[str] = None, end: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Return raw rows (as dict) from table applying optional start/end filters on detected timestamp column."""
    sites = discover_sites()
    if site not in sites:
        raise FileNotFoundError(f"site not found: {site}")
    db = sites[site]
    cols = get_table_columns(site, table)
    if not cols:
        return []
    ts_col = _choose_timestamp_column(cols)
    col_names = [c[0] for c in cols]
    sel = ", ".join([f'"{c}"' for c in col_names])
    sql = f'SELECT {sel} FROM "{table}"'
    params: List = []
    if start is not None or end is not None:
        wheres = []
        if start is not None:
            wheres.append(f'"{ts_col}" >= ?')
            params.append(start)
        if end is not None:
            wheres.append(f'"{ts_col}" <= ?')
            params.append(end)
        sql += ' WHERE ' + ' AND '.join(wheres)
    sql += f' ORDER BY "{ts_col}" ASC LIMIT {int(limit)}'

    con = _connect(db)
    cur = con.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()
    results = []
    for r in rows:
        d = {}
        for i, name in enumerate(col_names):
            d[name] = r[i]
        results.append(d)
    return results


def get_farm_names() -> List[str]:
    """Return unique farm names derived from discovered site names."""
    sites = discover_sites()
    farms: set = set()
    for site in sites:
        # site names: kelmarsh_data_by_turbine, kelmarsh_status_by_turbine
        for suffix in ('_data_by_turbine', '_status_by_turbine'):
            if site.endswith(suffix):
                farms.add(site[: -len(suffix)])
    return sorted(farms)


def get_farm_turbines(farm: str) -> List[str]:
    """Return turbine table names for a farm's data site."""
    site = f'{farm}_data_by_turbine'
    try:
        return list_turbines(site)
    except FileNotFoundError:
        return []


def get_farm_time_range(farm: str) -> Dict:
    """Return earliest/latest timestamp across the first turbine of the farm."""
    site = f'{farm}_data_by_turbine'
    sites = discover_sites()
    if site not in sites:
        return {'earliest': None, 'latest': None, 'timestamp_column': None}
    turbines = list_turbines(site)
    if not turbines:
        return {'earliest': None, 'latest': None, 'timestamp_column': None}
    cols = get_table_columns(site, turbines[0])
    ts_col = _choose_timestamp_column(cols)
    con = _connect(sites[site])
    cur = con.cursor()
    cur.execute(f'SELECT MIN("{ts_col}"), MAX("{ts_col}") FROM "{turbines[0]}"')
    row = cur.fetchone()
    con.close()
    return {'earliest': row[0], 'latest': row[1], 'timestamp_column': ts_col}


def get_farm_columns(farm: str) -> Dict[str, List[str]]:
    """Return columns grouped by file type (data/status) for a farm."""
    result: Dict[str, List[str]] = {}
    for data_type in ('data', 'status'):
        site = f'{farm}_{data_type}_by_turbine'
        sites = discover_sites()
        if site not in sites:
            continue
        turbines = list_turbines(site)
        if not turbines:
            continue
        cols = get_table_columns(site, turbines[0])
        result[data_type] = [c[0] for c in cols]
    return result


def query_day_rows(
    farm: str,
    data_type: str,
    turbine: str,
    date_from: str,
    columns: List[str] = None,
    hour_from: Optional[int] = None,
    hour_to: Optional[int] = None,
    limit: int = 10000,
    date_to: Optional[str] = None,
) -> Dict:
    """Query rows for a specific farm/turbine/date range with optional hour filter.

    date_to defaults to date_from (single-day query).
    When querying multi-day ranges the hour_from/hour_to filters apply on the
    first and last day respectively; intermediate days are returned in full.
    """
    date_to = date_to or date_from
    site = f'{farm}_{data_type}_by_turbine'
    sites = discover_sites()
    if site not in sites:
        raise FileNotFoundError(f"site not found: {site}")
    all_cols = get_table_columns(site, turbine)
    col_names = [c[0] for c in all_cols]
    ts_col = _choose_timestamp_column(all_cols)

    # Select only requested columns (always include timestamp)
    if columns:
        sel_cols = [c for c in columns if c in col_names]
        if ts_col not in sel_cols:
            sel_cols = [ts_col] + sel_cols
    else:
        sel_cols = col_names

    h_from = hour_from if hour_from is not None else 0
    h_to   = hour_to   if hour_to   is not None else 23
    start  = f'{date_from} {h_from:02d}:00:00'
    end    = f'{date_to} {h_to:02d}:59:59'

    sel = ', '.join([f'"{c}"' for c in sel_cols])
    sql = (
        f'SELECT {sel} FROM "{turbine}"'
        f' WHERE "{ts_col}" >= ? AND "{ts_col}" <= ?'
        f' ORDER BY "{ts_col}" ASC LIMIT {int(limit)}'
    )

    con = _connect(sites[site])
    cur = con.cursor()
    cur.execute(sql, [start, end])
    rows = cur.fetchall()
    con.close()

    return {
        'columns':   sel_cols,
        'rows':      [list(r) for r in rows],
        'row_count': len(rows),
        'farm':      farm,
        'file_type': data_type,
        'date':      date_from,
        'date_to':   date_to,
        'turbine':   turbine,
    }


def aggregate(site: str, table: str, column: str, start: Optional[str] = None, end: Optional[str] = None, freq: str = 'hour') -> List[Dict]:
    """Aggregate numeric column by hour or day. Returns list of buckets with avg/min/max/count.

    `freq` can be 'hour' or 'day'. The function validates column name against table columns.
    """
    assert freq in ('hour', 'day')
    sites = discover_sites()
    if site not in sites:
        raise FileNotFoundError(f"site not found: {site}")
    db = sites[site]
    cols = get_table_columns(site, table)
    if not cols:
        return []
    col_names = [c[0] for c in cols]
    if column not in col_names:
        raise ValueError(f"column not found: {column}")
    ts_col = _choose_timestamp_column(cols)
    # build bucket expression
    if freq == 'hour':
        bucket_expr = f"strftime('%Y-%m-%dT%H:00:00', \"{ts_col}\")"
    else:
        bucket_expr = f"strftime('%Y-%m-%d', \"{ts_col}\")"
    sql = f'SELECT {bucket_expr} as bucket, AVG("{column}") as avg, MIN("{column}") as min, MAX("{column}") as max, COUNT(1) as count FROM "{table}"'
    params: List = []
    if start is not None or end is not None:
        wheres = []
        if start is not None:
            wheres.append(f'"{ts_col}" >= ?')
            params.append(start)
        if end is not None:
            wheres.append(f'"{ts_col}" <= ?')
            params.append(end)
        sql += ' WHERE ' + ' AND '.join(wheres)
    sql += ' GROUP BY bucket ORDER BY bucket'

    con = _connect(db)
    cur = con.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    con.close()
    out = []
    for b, a, mn, mx, cnt in rows:
        out.append({'bucket': b, 'avg': a, 'min': mn, 'max': mx, 'count': cnt})
    return out

