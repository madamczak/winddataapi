"""
Integration tests that run against the live API on the Raspberry Pi at
http://192.168.0.103:8000

Run with:
    pytest tests/test_pi_integration.py -v
"""

import pytest
import httpx

BASE_URL = "http://192.168.0.103:8000"

KELMARSH_START    = "2018-05-30 20:00:00"
KELMARSH_END      = "2018-05-30 22:00:00"
PENMANSHIEL_START = "2018-05-01 00:00:00"
PENMANSHIEL_END   = "2018-05-01 06:00:00"


def _query(farm: str, data_type: str, turbine: str, start: str, end: str):
    with httpx.Client(base_url=BASE_URL, timeout=120, verify=False) as client:
        return client.get(
            f"/farms/{farm}/{data_type}/turbines/{turbine}/query",
            params={"start": start, "end": end},
        )


# ---------------------------------------------------------------------------
# Test 1 – Kelmarsh data
# ---------------------------------------------------------------------------

def test_kelmarsh_data_query():
    response = _query("kelmarsh", "data", "turbine_2", KELMARSH_START, KELMARSH_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "kelmarsh"
    assert body["data_type"] == "data"
    assert body["turbine"] == "turbine_2"
    assert body["count"] > 0
    assert isinstance(body["rows"], list)

    for row in body["rows"]:
        ts = row.get("Date and time") or row.get("Timestamp") or row.get("Timestamp start")
        assert ts is not None
        assert KELMARSH_START <= ts <= KELMARSH_END


# ---------------------------------------------------------------------------
# Test 2 – Kelmarsh status
# ---------------------------------------------------------------------------

def test_kelmarsh_status_query():
    response = _query("kelmarsh", "status", "turbine_2", KELMARSH_START, KELMARSH_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "kelmarsh"
    assert body["data_type"] == "status"
    assert body["count"] >= 0
    assert isinstance(body["rows"], list)


# ---------------------------------------------------------------------------
# Test 3 – Penmanshiel data
# ---------------------------------------------------------------------------

def test_penmanshiel_data_query():
    response = _query("penmanshiel", "data", "turbine_1", PENMANSHIEL_START, PENMANSHIEL_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "penmanshiel"
    assert body["data_type"] == "data"
    assert body["count"] > 0
    assert isinstance(body["rows"], list)


# ---------------------------------------------------------------------------
# Test 4 – Penmanshiel status
# ---------------------------------------------------------------------------

def test_penmanshiel_status_query():
    response = _query("penmanshiel", "status", "turbine_1", PENMANSHIEL_START, PENMANSHIEL_END)
    assert response.status_code == 200

    body = response.json()
    assert body["farm"] == "penmanshiel"
    assert body["data_type"] == "status"
    assert body["count"] >= 0
    assert isinstance(body["rows"], list)

