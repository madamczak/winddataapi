FastAPI Wind Turbine Data API

- Run locally: python main.py 8000
- Endpoints:
  - GET /health
  - GET /sites
  - GET /sites/{site}/turbines
  - GET /sites/{site}/turbines/{turbine}/columns
  - GET /sites/{site}/turbines/{turbine}/data?start=&end=&limit=
  - GET /sites/{site}/turbines/{turbine}/aggregate?column=&freq=hour|day&start=&end=

Notes:
- The service reads sqlite files under data_by_turbine/ (site name derived from filename without extension).
- Timestamp column is auto-detected from common names like 'Date and time' or 'Timestamp start'.
- Use read-only DB connections.

