import time
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import Literal, Optional, List
from . import db
from .telemetry import get_logger, request_counter, error_counter, request_duration

log = get_logger("winddataAPI.api")

app = FastAPI(title='Wind Turbine Data API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _client_ip(request: Request) -> str:
    """Return real client IP, honouring X-Forwarded-For (set by Render's proxy)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    ip = _client_ip(request)
    response: Response = await call_next(request)
    duration = time.perf_counter() - start
    dur_ms = round(duration * 1000)
    labels = {
        "method":   request.method,
        "endpoint": request.url.path,
        "status":   str(response.status_code),
    }
    request_counter.add(1, labels)
    request_duration.record(duration, labels)
    if response.status_code >= 400:
        error_counter.add(1, labels)
    log.info(
        f"{request.method} {request.url.path} "
        f"status={response.status_code} ip={ip} duration_ms={dur_ms}",
        extra={"loki_ip": ip, "loki_endpoint": request.url.path},
    )
    return response


@app.get('/health')
def health():
    return {'status': 'ok'}


# ── Frontend-compatible endpoints ─────────────────────────────────────────────

@app.get('/wind-farms')
def get_wind_farms():
    """List all available wind farms with turbine counts."""
    farm_names = db.get_farm_names()
    result = []
    for farm in farm_names:
        turbines = db.get_farm_turbines(farm)
        result.append({
            'name':          farm.replace('_', ' ').title(),
            'directory':     farm,
            'turbine_count': len(turbines),
            'turbines':      turbines,
        })
    return {'wind_farms': result}


@app.get('/wind-farms/time-ranges')
def get_time_ranges():
    """Return earliest/latest datetime for each farm."""
    farm_names = db.get_farm_names()
    result = []
    for farm in farm_names:
        tr = db.get_farm_time_range(farm)
        result.append({'farm': farm, **tr})
    return {'time_ranges': result}


@app.get('/wind-farms/columns')
def get_columns():
    """Return columns grouped by file type (data/status) for each farm."""
    farm_names = db.get_farm_names()
    result = []
    for farm in farm_names:
        cols = db.get_farm_columns(farm)
        result.append({'farm': farm, 'columns_by_type': cols})
    return {'farms': result}


@app.get('/wind-farms/{farm}/data/{date}')
def get_day_data(
    request: Request,
    farm: str,
    date: str,
    file_type: str = Query('data', description="'data' or 'status'"),
    turbine: Optional[str] = Query(None, description='Turbine table name, e.g. turbine_1'),
    columns: List[str] = Query([], description='Columns to return; empty = all'),
    hour_from: Optional[int] = Query(None, ge=0, le=23),
    hour_to:   Optional[int] = Query(None, ge=0, le=23),
):
    """Fetch rows for a farm/turbine/date with optional column + hour filters."""
    from .telemetry import rows_returned
    ip = _client_ip(request)
    if not turbine:
        turbines = db.get_farm_turbines(farm)
        if not turbines:
            raise HTTPException(404, f"No turbines found for farm '{farm}'")
        turbine = turbines[0]
    try:
        t0     = time.perf_counter()
        result = db.query_day_rows(farm, file_type, turbine, date, columns or [], hour_from, hour_to)
        dur_ms = round((time.perf_counter() - t0) * 1000)
        count  = len(result.get("rows", []))
        labels = {"farm": farm, "turbine": turbine, "file_type": file_type}
        rows_returned.record(count, labels)
        log.info(
            f"query farm={farm} turbine={turbine} date={date} "
            f"hours={hour_from}-{hour_to} type={file_type} "
            f"rows={count} duration_ms={dur_ms} ip={ip}",
            extra={
                "loki_farm": farm,
                "loki_turbine": turbine,
                "loki_file_type": file_type,
                "loki_ip": ip,
            },
        )
        return result
    except FileNotFoundError as exc:
        log.warning(f"Not found: farm={farm} turbine={turbine} date={date} ip={ip} — {exc}")
        raise HTTPException(404, str(exc))
    except Exception as exc:
        log.error(f"Error: farm={farm} turbine={turbine} date={date} ip={ip} — {exc}")
        raise HTTPException(500, str(exc))


@app.get('/wind-farms/{farm}/{turbine}/event-types')
def get_event_types(farm: str, turbine: str):
    """Return distinct IEC category values available in the status table for a turbine."""
    site = f'{farm}_status_by_turbine'
    sites = db.discover_sites()
    if site not in sites:
        raise HTTPException(404, f"Status site not found for farm '{farm}'")
    try:
        con = db._connect(sites[site])
        cur = con.cursor()
        cur.execute(f'SELECT DISTINCT "IEC category" FROM "{turbine}" WHERE "IEC category" IS NOT NULL ORDER BY "IEC category"')
        types = [r[0] for r in cur.fetchall()]
        con.close()
        return {'event_types': types}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get('/wind-farms/{farm}/{turbine}/events')
def get_events(
    farm: str,
    turbine: str,
    iec_category: Optional[str] = Query(None, description='Filter by IEC category, e.g. "Full Performance"'),
    status: Optional[str] = Query(None, description='Filter by Status value'),
    limit: int = Query(500, ge=1, le=5000),
):
    """Return events (status records) for a turbine, optionally filtered by IEC category."""
    site = f'{farm}_status_by_turbine'
    sites = db.discover_sites()
    if site not in sites:
        raise HTTPException(404, f"Status site not found for farm '{farm}'")
    try:
        con = db._connect(sites[site])
        cur = con.cursor()
        # Get column names
        cur.execute(f'PRAGMA table_info("{turbine}")')
        cols = [r[1] for r in cur.fetchall()]
        where_clauses = []
        params = []
        if iec_category:
            where_clauses.append('"IEC category" = ?')
            params.append(iec_category)
        if status:
            where_clauses.append('"Status" = ?')
            params.append(status)
        where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
        ts_col = 'Timestamp start' if 'Timestamp start' in cols else cols[0]
        sel = ', '.join([f'"{c}"' for c in cols])
        sql = f'SELECT {sel} FROM "{turbine}" {where_sql} ORDER BY "{ts_col}" DESC LIMIT {int(limit)}'
        cur.execute(sql, params)
        rows = cur.fetchall()
        con.close()
        events = [dict(zip(cols, row)) for row in rows]
        return {'farm': farm, 'turbine': turbine, 'columns': cols, 'events': events, 'count': len(events)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get(
    '/farms/{farm}/{data_type}/turbines/{turbine}/query',
    summary='Query turbine data or status for a wind farm between a start and end datetime',
)
def farm_turbine_query(
    request: Request,
    farm: str,
    data_type: Literal['data', 'status'],
    turbine: str,
    start: Optional[str] = Query(None, description='Start datetime, e.g. 2018-05-30 20:00:00'),
    end: Optional[str] = Query(None, description='End datetime, e.g. 2018-05-30 22:00:00'),
    limit: int = Query(1000, ge=1, le=50000),
):
    """
    Query turbine **data** or **status** for a given wind farm.

    - `farm` – farm name, e.g. `kelmarsh` or `penmanshiel`
    - `data_type` – `data` or `status`
    - `turbine` – turbine table name, e.g. `turbine_2`
    - `start` / `end` – optional ISO datetime bounds (inclusive)
    """
    site = f'{farm}_{data_type}_by_turbine'
    ip = _client_ip(request)
    try:
        from .telemetry import rows_returned
        t0   = time.perf_counter()
        rows = db.query_rows(site, turbine, start=start, end=end, limit=limit)
        dur_ms = round((time.perf_counter() - t0) * 1000)
        labels = {"farm": farm, "turbine": turbine, "data_type": data_type}
        rows_returned.record(len(rows), labels)
        log.info(
            f"query farm={farm} turbine={turbine} type={data_type} "
            f"start={start} end={end} rows={len(rows)} duration_ms={dur_ms} ip={ip}",
            extra={
                "loki_farm": farm,
                "loki_turbine": turbine,
                "loki_data_type": data_type,
                "loki_ip": ip,
            },
        )
        return {
            'farm': farm,
            'data_type': data_type,
            'turbine': turbine,
            'start': start,
            'end': end,
            'count': len(rows),
            'rows': rows,
        }
    except FileNotFoundError:
        available = [s for s in db.discover_sites() if s.startswith(farm)]
        log.warning(f"Site not found: {site} ip={ip} — available: {available}")
        raise HTTPException(
            status_code=404,
            detail=f"Site '{site}' not found. Available sites matching farm '{farm}': {available}",
        )
    except Exception as e:
        log.error(f"Error querying {site}/{turbine} ip={ip}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
