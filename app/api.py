from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal, Optional, List
from . import db

app = FastAPI(title='Wind Turbine Data API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


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
    farm: str,
    date: str,
    file_type: str = Query('data', description="'data' or 'status'"),
    turbine: Optional[str] = Query(None, description='Turbine table name, e.g. turbine_1'),
    columns: List[str] = Query([], description='Columns to return; empty = all'),
    hour_from: Optional[int] = Query(None, ge=0, le=23),
    hour_to:   Optional[int] = Query(None, ge=0, le=23),
):
    """Fetch rows for a farm/turbine/date with optional column + hour filters."""
    # Default to first available turbine when none specified
    if not turbine:
        turbines = db.get_farm_turbines(farm)
        if not turbines:
            raise HTTPException(404, f"No turbines found for farm '{farm}'")
        turbine = turbines[0]
    try:
        return db.query_day_rows(farm, file_type, turbine, date, columns or [], hour_from, hour_to)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get(
    '/farms/{farm}/{data_type}/turbines/{turbine}/query',
    summary='Query turbine data or status for a wind farm between a start and end datetime',
)
def farm_turbine_query(
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
    try:
        rows = db.query_rows(site, turbine, start=start, end=end, limit=limit)
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
        raise HTTPException(
            status_code=404,
            detail=f"Site '{site}' not found. Available sites matching farm '{farm}': {available}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
