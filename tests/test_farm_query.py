"""
Integration tests for the /farms/{farm}/{data_type}/turbines/{turbine}/query endpoint.
Runs against the live API at https://winddataapi-backend.onrender.com
"""

import pytest
import httpx

pytestmark = pytest.mark.anyio

BASE_URL = "https://winddataapi-backend.onrender.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KELMARSH_START    = "2018-05-30 20:00:00"
KELMARSH_END      = "2018-05-30 22:00:00"
PENMANSHIEL_START = "2018-05-01 00:00:00"
PENMANSHIEL_END   = "2018-05-01 06:00:00"


async def _query(farm: str, data_type: str, turbine: str, start: str, end: str):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        return await client.get(
            f"/farms/{farm}/{data_type}/turbines/{turbine}/query",
            params={"start": start, "end": end},
        )


# ---------------------------------------------------------------------------
# Test 1 – Kelmarsh data
# ---------------------------------------------------------------------------

async def test_kelmarsh_data_query():
    response = await _query("kelmarsh", "data", "turbine_2", KELMARSH_START, KELMARSH_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "kelmarsh"
    assert body["data_type"] == "data"
    assert body["turbine"] == "turbine_2"
    assert body["start"] == KELMARSH_START
    assert body["end"] == KELMARSH_END
    assert body["count"] > 0
    assert isinstance(body["rows"], list)

    # Every returned row must fall within the requested window
    for row in body["rows"]:
        ts = row.get("Date and time") or row.get("Timestamp") or row.get("Timestamp start")
        assert ts is not None
        assert KELMARSH_START <= ts <= KELMARSH_END


# ---------------------------------------------------------------------------
# Test 2 – Kelmarsh status
# ---------------------------------------------------------------------------

async def test_kelmarsh_status_query():
    response = await _query("kelmarsh", "status", "turbine_2", KELMARSH_START, KELMARSH_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "kelmarsh"
    assert body["data_type"] == "status"
    assert body["count"] >= 0       # status table may have fewer rows
    assert isinstance(body["rows"], list)


# ---------------------------------------------------------------------------
# Test 3 – Penmanshiel data
# ---------------------------------------------------------------------------

async def test_penmanshiel_data_query():
    response = await _query("penmanshiel", "data", "turbine_1", PENMANSHIEL_START, PENMANSHIEL_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "penmanshiel"
    assert body["data_type"] == "data"
    assert body["count"] > 0
    assert isinstance(body["rows"], list)

    for row in body["rows"]:
        ts = row.get("Date and time") or row.get("Timestamp") or row.get("Timestamp start")
        assert ts is not None
        assert PENMANSHIEL_START <= ts <= PENMANSHIEL_END


# ---------------------------------------------------------------------------
# Test 4 – Penmanshiel status
# ---------------------------------------------------------------------------

async def test_penmanshiel_status_query():
    response = await _query("penmanshiel", "status", "turbine_1", PENMANSHIEL_START, PENMANSHIEL_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "penmanshiel"
    assert body["data_type"] == "status"
    assert body["count"] >= 0
    assert isinstance(body["rows"], list)


# ---------------------------------------------------------------------------
# Bonus – 404 for an unknown farm
# ---------------------------------------------------------------------------

async def test_unknown_farm_returns_404():
    response = await _query("unknown_farm", "data", "turbine_1", "2018-01-01", "2018-01-02")
    assert response.status_code == 404

