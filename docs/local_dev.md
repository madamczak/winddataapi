# Local Development — API + Frontend

Quick guide to running the full stack locally using the bundled example databases.

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| npm | 9+ |

---

## 1 — Clone & install

```bash
git clone https://github.com/madamczak/winddataapi.git
cd winddataapi
```

**Python dependencies** (from project root):
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

**Frontend dependencies:**
```bash
cd frontend
npm install
cd ..
```

---

## 2 — Start the API with example data

The example databases live in `data_by_turbine_example/` and cover
**2019-07-01 → 2019-07-07** for two wind farms:

| Farm | Turbines | DB files |
|---|---|---|
| kelmarsh | 6 | `kelmarsh_data_by_turbine.db`, `kelmarsh_status_by_turbine.db` |
| penmanshiel | 15 | `penmanshiel_data_by_turbine.db`, `penmanshiel_status_by_turbine.db` |

Point the API at the example directory via the `DATA_DIR` environment variable:

**Windows (PowerShell):**
```powershell
$env:DATA_DIR = "data_by_turbine_example"
$env:ENVIRONMENT = "local"
python main.py
```

**macOS / Linux:**
```bash
DATA_DIR=data_by_turbine_example ENVIRONMENT=local python main.py
```

> **Grafana note:** when `ENVIRONMENT` is anything other than `production` the
> logger name becomes `winddataAPI.local` (instead of `winddataAPI`).  
> This means Loki streams and Grafana dashboard series are immediately
> distinguishable from production logs — filter by `app="winddataAPI.local"`
> for local runs and `app="winddataAPI"` for production.

The API starts on **http://localhost:8000**.  
Interactive docs: **http://localhost:8000/docs**

### Quick smoke-test
```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl "http://localhost:8000/wind-farms"
# lists kelmarsh and penmanshiel

curl "http://localhost:8000/wind-farms/kelmarsh/data/2019-07-03"
# returns turbine_1 rows for 2019-07-03
```

---

## 3 — Start the frontend

In a **second terminal**, from the `frontend/` directory:

```bash
cd frontend
npm run dev
```

The Vite dev server starts on **http://localhost:5173**.  
It automatically proxies all `/wind-farms/*` requests to the API on port 8000
(configured in `frontend/vite.config.js`) so no CORS issues.

Open **http://localhost:5173** in your browser.

---

## 4 — Regenerate example databases

If you need to recreate the databases from scratch (e.g. after changing the
generator script):

```bash
python scripts/generate_example_dbs.py
```

The generator uses `random.seed(42)` so the output is fully reproducible.

---

## 5 — Run with real data

To use the full production databases instead, either omit `DATA_DIR` (defaults
to `data_by_turbine/`) or set it explicitly:

```powershell
$env:DATA_DIR = "data_by_turbine"
python main.py
```

