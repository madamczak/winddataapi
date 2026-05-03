# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY main.py .

# ── Runtime configuration ─────────────────────────────────────────────────────
# DATA_DIR — path to the folder containing the SQLite .db files.
# Mount your data volume here, e.g.:
#   docker run -e DATA_DIR=/data -v /host/path/data_by_turbine:/data ...
ENV DATA_DIR=/data

# Expose FastAPI port
EXPOSE 8000

# Start the API
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

