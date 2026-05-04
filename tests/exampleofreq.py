import requests

BASE = "https://winddataapi-backend.onrender.com"


def get(url, **kwargs):
    r = requests.get(url, **kwargs)
    try:
        body = r.json()
    except Exception:
        body = r.text or "<empty body>"
    print(f"  status: {r.status_code}")
    return r, body


# Health check
print("\n--- /health ---")
r, body = get(f"{BASE}/health")
print(f"  response: {body}")

# List wind farms
print("\n--- /wind-farms ---")
r, body = get(f"{BASE}/wind-farms")
farms = body.get("wind_farms", []) if isinstance(body, dict) else []
for f in farms:
    print(f"  {f.get('directory')} — {f.get('turbine_count')} turbines: {f.get('turbines', [])}")

# Time ranges
print("\n--- /wind-farms/time-ranges ---")
r, body = get(f"{BASE}/wind-farms/time-ranges")
for tr in (body.get("time_ranges", []) if isinstance(body, dict) else []):
    print(f"  {tr.get('farm')}: {tr.get('earliest')} → {tr.get('latest')}")

# Available columns (summarised)
print("\n--- /wind-farms/columns ---")
r, body = get(f"{BASE}/wind-farms/columns")
for farm in (body.get("farms", []) if isinstance(body, dict) else []):
    for ftype, cols in farm.get("columns_by_type", {}).items():
        print(f"  {farm['farm']}/{ftype}: {len(cols)} columns")

# Day data — kelmarsh, turbine_2, hours 8-10
print("\n--- /wind-farms/kelmarsh/data/2018-05-30 (turbine_2, 08-10) ---")
r, body = get(f"{BASE}/wind-farms/kelmarsh/data/2018-05-30", params={
    "turbine": "turbine_2",
    "hour_from": 8,
    "hour_to": 10,
})
if isinstance(body, dict):
    count = body.get("row_count", body.get("count", "?"))
    print(f"  rows returned: {count}")
    if body.get("rows"):
        print(f"  first row: {body['rows'][0]}")
else:
    print(f"  error: {body}")

# Legacy query endpoint — kelmarsh, turbine_2, 20:00-22:00
print("\n--- /farms/kelmarsh/data/turbines/turbine_2/query ---")
r, body = get(f"{BASE}/farms/kelmarsh/data/turbines/turbine_2/query", params={
    "start": "2018-05-30 20:00:00",
    "end":   "2018-05-30 22:00:00",
})
if isinstance(body, dict):
    print(f"  rows returned: {body.get('count', '?')}")
else:
    print(f"  error: {body}")

# Status query
print("\n--- /farms/kelmarsh/status/turbines/turbine_2/query ---")
r, body = get(f"{BASE}/farms/kelmarsh/status/turbines/turbine_2/query", params={
    "start": "2018-05-30 20:00:00",
    "end":   "2018-05-30 22:00:00",
})
if isinstance(body, dict):
    print(f"  rows returned: {body.get('count', '?')}")
else:
    print(f"  error: {body}")

