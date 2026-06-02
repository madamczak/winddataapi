"""
Generate data_by_turbine_example/ — synthetic SCADA data for July 1-7 2019.

Output (data_by_turbine_example/):
  kelmarsh_data_by_turbine.db      — 6 turbines, per-turbine tables
  kelmarsh_status_by_turbine.db    — 6 turbines, per-turbine event tables
  penmanshiel_data_by_turbine.db   — 15 turbines, per-turbine tables
  penmanshiel_status_by_turbine.db — 15 turbines, per-turbine event tables

Date range : 2019-07-01 00:00:00 → 2019-07-07 23:50:00 (7 days, 10-min intervals)
Rows/turbine: 1008

Schema mirrors the real production databases exactly so the existing crawler
and API code work unchanged.
"""

import math
import os
import random
import sqlite3
from datetime import datetime, timedelta

random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data_by_turbine_example")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Time range ───────────────────────────────────────────────────────────────
START = datetime(2019, 7, 1, 0, 0, 0)
END   = datetime(2019, 7, 7, 23, 50, 0)
STEP  = timedelta(minutes=10)

TS_LIST = []
t = START
while t <= END:
    TS_LIST.append(t)
    t += STEP

print(f"Timestamps per turbine: {len(TS_LIST)}")  # 1008


# ── Physics helpers ──────────────────────────────────────────────────────────

def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt_dur(seconds: int) -> str:
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def wind_speed(dt: datetime, base: float = 7.5) -> float:
    """Diurnal sinusoidal + Gaussian noise. Returns m/s in [0, 25]."""
    hour = dt.hour + dt.minute / 60.0
    diurnal = 2.5 * math.sin(2 * math.pi * (hour - 14) / 24)
    ws = base + diurnal + random.gauss(0, 1.8)
    return round(max(0.0, min(25.0, ws)), 2)


def power_kw(ws: float, rated: float = 2050.0,
             cut_in: float = 3.0, rated_ws: float = 13.0) -> float:
    """Cubic power curve; 0 below cut-in or above 25 m/s."""
    if ws < cut_in or ws > 25.0:
        return 0.0
    if ws >= rated_ws:
        return round(rated + random.gauss(0, 10), 2)
    frac = ((ws - cut_in) / (rated_ws - cut_in)) ** 3
    return round(max(0.0, rated * frac + random.gauss(0, 15)), 2)


def gen_rpm(ws: float, rated_rpm: float = 1200.0, rated_ws: float = 13.0) -> float:
    if ws < 3.0:
        return 0.0
    return round(min(rated_rpm, rated_rpm * ws / rated_ws), 1)


def rotor_rpm(g: float, ratio: float = 87.0) -> float:
    return round(g / ratio, 2)


def nacelle_temp(dt: datetime) -> float:
    hour = dt.hour + dt.minute / 60.0
    return round(35.0 + 5 * math.sin(2 * math.pi * hour / 24) + random.gauss(0, 1.5), 2)


def ambient_temp(dt: datetime) -> float:
    hour = dt.hour + dt.minute / 60.0
    return round(17.0 + 4 * math.sin(2 * math.pi * (hour - 14) / 24) + random.gauss(0, 0.8), 2)


def wind_dir() -> float:
    """Prevailing SW, ~225 degrees."""
    return round(random.gauss(225, 45) % 360, 2)


def pitch_angle(ws: float) -> float:
    if ws < 3.0:
        return round(random.uniform(80, 90), 2)
    if ws >= 13.0:
        return round(min(45.0, (ws - 13.0) * 2.5) + random.gauss(0, 0.3), 2)
    return round(max(0.0, random.gauss(1.0, 0.5)), 2)


# ── Status event generation ──────────────────────────────────────────────────

_STATUS_POOL = [
    ("Informational", 0,    "System OK",                "System OK (32)",           "Full Performance"),
    ("Informational", 10,   "Wind < start wind",        "External stop (5)",        "Out of Environmental Specification"),
    ("Warning",       100,  "High vibration - nacelle", "Operating states (28)",    "Technical Standby"),
    ("Stop",          6200, "Cable autounwind",         "Operating states (28)",    "Technical Standby"),
    ("Fault",         3100, "Grid fault",               "Grid-caused downtime (3)", "Force Majeure"),
]
_STATUS_WEIGHTS = [55, 20, 10, 10, 5]


def _gen_status_events(n_turbine: int, cols_include_global: bool):
    """Return a list of status event rows covering START to END."""
    rows = []
    cur = START
    month_end = END + STEP
    while cur < month_end:
        ev = random.choices(_STATUS_POOL, weights=_STATUS_WEIGHTS, k=1)[0]
        status_txt, code, msg, svc_cat, iec_cat = ev
        if code == 0:
            dur = timedelta(hours=random.randint(2, 48))
        elif code == 10:
            dur = timedelta(minutes=random.randint(5, 90))
        else:
            dur = timedelta(hours=random.randint(1, 12))
        end_t = min(cur + dur, month_end)
        secs = int((end_t - cur).total_seconds())
        row = [fmt(cur), fmt(end_t), fmt_dur(secs),
               status_txt, str(code), msg, None, svc_cat, iec_cat]
        if cols_include_global:
            row.append(svc_cat)   # Global contract category (Kelmarsh only)
        row.append(n_turbine)
        rows.append(row)
        cur = end_t
    return rows


# ── Column definitions ────────────────────────────────────────────────────────

KELMARSH_COLS = [
    "src_rowid", "turbine",
    "Date and time",
    "Wind speed (m/s)", "Wind speed, Standard deviation (m/s)",
    "Wind speed, Minimum (m/s)", "Wind speed, Maximum (m/s)",
    "Wind direction ()", "Nacelle position ()",
    "Energy Export (kWh)", "Energy Export counter (kWh)", "Energy Import (kWh)",
    "Power (kW)", "Power, Standard deviation (kW)", "Power, Minimum (kW)", "Power, Maximum (kW)",
    "Potential power default PC (kW)", "Turbine Power setpoint (kW)",
    "Available Capacity for Production (kW)",
    "Nacelle ambient temperature (C)", "Nacelle temperature (C)",
    "Gear oil temperature (C)", "Front bearing temperature (C)",
    "Rear bearing temperature (C)", "Stator temperature 1 (C)",
    "Transformer temperature (C)", "Generator bearing front temperature (C)",
    "Generator bearing rear temperature (C)",
    "Generator RPM (RPM)", "Rotor speed (RPM)", "Gearbox speed (RPM)",
    "Generator RPM, Max (RPM)", "Generator RPM, Min (RPM)",
    "Rotor speed, Max (RPM)", "Rotor speed, Min (RPM)",
    "Grid voltage (V)", "Grid current (A)", "Grid frequency (Hz)",
    "Power factor (cosphi)", "Reactive power (kvar)",
    "Blade angle (pitch position) A ()",
    "Blade angle (pitch position) B ()",
    "Blade angle (pitch position) C ()",
    "Yaw bearing angle ()",
    "Gear oil inlet pressure (bar)", "Gear oil pump pressure (bar)",
    "Capacity factor", "Data Availability",
    "Time-based Contractual Avail.", "Time-based IEC B.2.2 (Users View)",
    "Production-based IEC B.2.2 (Users View)",
    "Time-based System Avail.", "Production-based System Avail.",
    "Reactive Energy Export (kvarh)",
    "Equivalent Full Load Hours (s)",
    "Night Time",
]

PENMANSHIEL_COLS = [
    "Date and time",
    "Wind speed (m/s)", "Wind speed, Standard deviation (m/s)",
    "Wind speed, Minimum (m/s)", "Wind speed, Maximum (m/s)",
    "Wind direction ()", "Nacelle position ()",
    "Energy Export (kWh)", "Energy Export counter (kWh)", "Energy Import (kWh)",
    "Power (kW)", "Power, Standard deviation (kW)", "Power, Minimum (kW)", "Power, Maximum (kW)",
    "Potential power default PC (kW)", "Turbine Power setpoint (kW)",
    "Available Capacity for Production (kW)",
    "APE-2 (kW)",
    "Nacelle ambient temperature (C)", "Nacelle temperature (C)",
    "Gear oil temperature (C)", "Front bearing temperature (C)",
    "Rear bearing temperature (C)", "Stator temperature 1 (C)",
    "Transformer temperature (C)", "Generator bearing front temperature (C)",
    "Generator bearing rear temperature (C)",
    "Generator RPM (RPM)", "Rotor speed (RPM)", "Gearbox speed (RPM)",
    "Generator RPM, Max (RPM)", "Generator RPM, Min (RPM)",
    "Rotor speed, Max (RPM)", "Rotor speed, Min (RPM)",
    "Grid voltage (V)", "Grid current (A)", "Grid frequency (Hz)",
    "Power factor (cosphi)", "Reactive power (kvar)",
    "Blade angle (pitch position) A ()",
    "Blade angle (pitch position) B ()",
    "Blade angle (pitch position) C ()",
    "Yaw bearing angle ()",
    "Gear oil inlet pressure (bar)", "Gear oil pump pressure (bar)",
    "Capacity factor", "Data Availability",
    "Time-based Contractual Avail.", "Time-based IEC B.2.2 (Users View)",
    "Production-based IEC B.2.2 (Users View)",
    "Time-based System Avail.", "Production-based System Avail.",
    "Reactive Energy Export (kvarh)",
    "Equivalent Full Load Hours (s)",
    "Turbine",
]

STATUS_COLS_KELMARSH = [
    "Timestamp start", "Timestamp end", "Duration",
    "Status", "Code", "Message", "Comment",
    "Service contract category", "IEC category",
    "Global contract category",
    "Turbine",
]

STATUS_COLS_PENMANSHIEL = [
    "Timestamp start", "Timestamp end", "Duration",
    "Status", "Code", "Message", "Comment",
    "Service contract category", "IEC category",
    "Turbine",
]


def _phs(cols):
    return ", ".join("?" for _ in cols)


# ── Row builders ─────────────────────────────────────────────────────────────

def _kelmarsh_row(t_num: int, dt: datetime, src_id: int, energy_kwh: float) -> list:
    ws = wind_speed(dt, base=7.5 + t_num * 0.1)
    pwr = power_kw(ws)
    export = round(pwr / 6, 3)
    g_rpm = gen_rpm(ws)
    r_rpm = rotor_rpm(g_rpm)
    nac_t = nacelle_temp(dt)
    amb_t = ambient_temp(dt)
    wd = wind_dir()
    pa = pitch_angle(ws)
    grid_v = round(400.0 + random.gauss(0, 1.5), 2)
    current = round(pwr / (math.sqrt(3) * grid_v) * 1000, 2) if pwr > 0 else 0.0
    freq = round(50.0 + random.gauss(0, 0.015), 4)
    avail = 1.0
    cap = round(pwr / 2050.0, 4)
    gear_t = round(50 + pwr / 2050 * 20 + random.gauss(0, 0.8), 2)
    brg_t = round(45 + pwr / 2050 * 15 + random.gauss(0, 1.5), 2)

    d = {col: None for col in KELMARSH_COLS}
    d["src_rowid"] = src_id
    d["turbine"] = t_num
    d["Date and time"] = fmt(dt)
    d["Wind speed (m/s)"] = ws
    d["Wind speed, Standard deviation (m/s)"] = round(ws * 0.1, 3)
    d["Wind speed, Minimum (m/s)"] = round(max(0.0, ws - 0.5), 2)
    d["Wind speed, Maximum (m/s)"] = round(ws + 0.5, 2)
    d["Wind direction ()"] = wd
    d["Nacelle position ()"] = round(wd + random.gauss(0, 4), 2)
    d["Energy Export (kWh)"] = export
    d["Energy Export counter (kWh)"] = round(energy_kwh + export, 1)
    d["Energy Import (kWh)"] = 0.0
    d["Power (kW)"] = pwr
    d["Power, Standard deviation (kW)"] = round(pwr * 0.04, 2)
    d["Power, Minimum (kW)"] = round(pwr * 0.92, 2)
    d["Power, Maximum (kW)"] = round(pwr * 1.08, 2)
    d["Potential power default PC (kW)"] = round(power_kw(ws) * 1.01, 2)
    d["Turbine Power setpoint (kW)"] = 2050.0
    d["Available Capacity for Production (kW)"] = 2050.0
    d["Nacelle ambient temperature (C)"] = amb_t
    d["Nacelle temperature (C)"] = nac_t
    d["Gear oil temperature (C)"] = gear_t
    d["Front bearing temperature (C)"] = round(brg_t - 5, 2)
    d["Rear bearing temperature (C)"] = round(brg_t - 3, 2)
    d["Stator temperature 1 (C)"] = round(nac_t + 15 + pwr / 2050 * 25, 2)
    d["Transformer temperature (C)"] = round(amb_t + 20 + pwr / 2050 * 30, 2)
    d["Generator bearing front temperature (C)"] = brg_t
    d["Generator bearing rear temperature (C)"] = round(brg_t - 2, 2)
    d["Generator RPM (RPM)"] = g_rpm
    d["Rotor speed (RPM)"] = r_rpm
    d["Gearbox speed (RPM)"] = round(g_rpm * 0.95, 1)
    d["Generator RPM, Max (RPM)"] = round(g_rpm * 1.02, 1)
    d["Generator RPM, Min (RPM)"] = round(g_rpm * 0.98, 1)
    d["Rotor speed, Max (RPM)"] = round(r_rpm * 1.02, 2)
    d["Rotor speed, Min (RPM)"] = round(r_rpm * 0.98, 2)
    d["Grid voltage (V)"] = grid_v
    d["Grid current (A)"] = current
    d["Grid frequency (Hz)"] = freq
    d["Power factor (cosphi)"] = round(-0.95 + random.gauss(0, 0.005), 4)
    d["Reactive power (kvar)"] = round(-pwr * 0.15, 2)
    d["Blade angle (pitch position) A ()"] = pa
    d["Blade angle (pitch position) B ()"] = round(pa + random.gauss(0, 0.08), 2)
    d["Blade angle (pitch position) C ()"] = round(pa + random.gauss(0, 0.08), 2)
    d["Yaw bearing angle ()"] = d["Nacelle position ()"]
    d["Gear oil inlet pressure (bar)"] = round(2.5 + random.gauss(0, 0.08), 3)
    d["Gear oil pump pressure (bar)"] = round(3.5 + random.gauss(0, 0.08), 3)
    d["Capacity factor"] = cap
    d["Data Availability"] = 1
    d["Time-based Contractual Avail."] = avail
    d["Time-based IEC B.2.2 (Users View)"] = avail
    d["Production-based IEC B.2.2 (Users View)"] = avail if pwr > 0 else 0.0
    d["Time-based System Avail."] = avail
    d["Production-based System Avail."] = avail if pwr > 0 else 0.0
    d["Reactive Energy Export (kvarh)"] = round(abs(d["Reactive power (kvar)"]) / 6, 3)
    d["Equivalent Full Load Hours (s)"] = round(export / 2050 * 3600, 1) if export > 0 else 0.0
    d["Night Time"] = 0 if 6 <= dt.hour <= 21 else 1
    return [d[c] for c in KELMARSH_COLS]


def _penmanshiel_row(t_num: int, dt: datetime, energy_kwh: float) -> list:
    ws = wind_speed(dt, base=7.2 + t_num * 0.08)
    pwr = power_kw(ws)
    export = round(pwr / 6, 3)
    g_rpm = gen_rpm(ws)
    r_rpm = rotor_rpm(g_rpm)
    nac_t = nacelle_temp(dt)
    amb_t = ambient_temp(dt)
    wd = wind_dir()
    pa = pitch_angle(ws)
    grid_v = round(690.0 + random.gauss(0, 1.5), 2)
    current = round(pwr / (math.sqrt(3) * grid_v) * 1000, 2) if pwr > 0 else 0.0
    freq = round(50.0 + random.gauss(0, 0.015), 4)
    avail = 1.0
    cap = round(pwr / 2050.0, 4)
    gear_t = round(50 + pwr / 2050 * 20 + random.gauss(0, 0.8), 2)
    brg_t = round(45 + pwr / 2050 * 15 + random.gauss(0, 1.5), 2)

    d = {col: None for col in PENMANSHIEL_COLS}
    d["Date and time"] = fmt(dt)
    d["Wind speed (m/s)"] = ws
    d["Wind speed, Standard deviation (m/s)"] = round(ws * 0.1, 3)
    d["Wind speed, Minimum (m/s)"] = round(max(0.0, ws - 0.5), 2)
    d["Wind speed, Maximum (m/s)"] = round(ws + 0.5, 2)
    d["Wind direction ()"] = wd
    d["Nacelle position ()"] = round(wd + random.gauss(0, 4), 2)
    d["Energy Export (kWh)"] = export
    d["Energy Export counter (kWh)"] = round(energy_kwh + export, 1)
    d["Energy Import (kWh)"] = 0.0
    d["Power (kW)"] = pwr
    d["Power, Standard deviation (kW)"] = round(pwr * 0.04, 2)
    d["Power, Minimum (kW)"] = round(pwr * 0.92, 2)
    d["Power, Maximum (kW)"] = round(pwr * 1.08, 2)
    d["Potential power default PC (kW)"] = round(power_kw(ws) * 1.01, 2)
    d["Turbine Power setpoint (kW)"] = 2050.0
    d["Available Capacity for Production (kW)"] = 2050.0
    d["APE-2 (kW)"] = round(pwr * 1.01, 2)
    d["Nacelle ambient temperature (C)"] = amb_t
    d["Nacelle temperature (C)"] = nac_t
    d["Gear oil temperature (C)"] = gear_t
    d["Front bearing temperature (C)"] = round(brg_t - 5, 2)
    d["Rear bearing temperature (C)"] = round(brg_t - 3, 2)
    d["Stator temperature 1 (C)"] = round(nac_t + 15 + pwr / 2050 * 25, 2)
    d["Transformer temperature (C)"] = round(amb_t + 20 + pwr / 2050 * 30, 2)
    d["Generator bearing front temperature (C)"] = brg_t
    d["Generator bearing rear temperature (C)"] = round(brg_t - 2, 2)
    d["Generator RPM (RPM)"] = g_rpm
    d["Rotor speed (RPM)"] = r_rpm
    d["Gearbox speed (RPM)"] = round(g_rpm * 0.95, 1)
    d["Generator RPM, Max (RPM)"] = round(g_rpm * 1.02, 1)
    d["Generator RPM, Min (RPM)"] = round(g_rpm * 0.98, 1)
    d["Rotor speed, Max (RPM)"] = round(r_rpm * 1.02, 2)
    d["Rotor speed, Min (RPM)"] = round(r_rpm * 0.98, 2)
    d["Grid voltage (V)"] = grid_v
    d["Grid current (A)"] = current
    d["Grid frequency (Hz)"] = freq
    d["Power factor (cosphi)"] = round(-0.94 + random.gauss(0, 0.005), 4)
    d["Reactive power (kvar)"] = round(-pwr * 0.14, 2)
    d["Blade angle (pitch position) A ()"] = pa
    d["Blade angle (pitch position) B ()"] = round(pa + random.gauss(0, 0.08), 2)
    d["Blade angle (pitch position) C ()"] = round(pa + random.gauss(0, 0.08), 2)
    d["Yaw bearing angle ()"] = d["Nacelle position ()"]
    d["Gear oil inlet pressure (bar)"] = round(2.5 + random.gauss(0, 0.08), 3)
    d["Gear oil pump pressure (bar)"] = round(3.5 + random.gauss(0, 0.08), 3)
    d["Capacity factor"] = cap
    d["Data Availability"] = 1
    d["Time-based Contractual Avail."] = avail
    d["Time-based IEC B.2.2 (Users View)"] = avail
    d["Production-based IEC B.2.2 (Users View)"] = avail if pwr > 0 else 0.0
    d["Time-based System Avail."] = avail
    d["Production-based System Avail."] = avail if pwr > 0 else 0.0
    d["Reactive Energy Export (kvarh)"] = round(abs(d["Reactive power (kvar)"]) / 6, 3)
    d["Equivalent Full Load Hours (s)"] = round(export / 2050 * 3600, 1) if export > 0 else 0.0
    d["Turbine"] = str(t_num)
    return [d[c] for c in PENMANSHIEL_COLS]


# ── Database builders ─────────────────────────────────────────────────────────

def _create_data_db(path: str, turbines: range, cols: list, row_fn, farm: str):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    ph = _phs(cols)
    for t_num in turbines:
        table = f"turbine_{t_num}"
        cur.execute(f'CREATE TABLE "{table}" ({col_defs})')
        energy = round(random.uniform(400_000, 2_000_000), 1)
        batch = []
        for i, dt in enumerate(TS_LIST):
            if farm == "kelmarsh":
                row = row_fn(t_num, dt, t_num * 100_000 + i, energy)
            else:
                row = row_fn(t_num, dt, energy)
            pwr = float(row[cols.index("Power (kW)")] or 0)
            energy += pwr / 6
            batch.append(row)
            if len(batch) >= 500:
                cur.executemany(f'INSERT INTO "{table}" VALUES ({ph})', batch)
                batch = []
        if batch:
            cur.executemany(f'INSERT INTO "{table}" VALUES ({ph})', batch)
        print(f"  turbine_{t_num}: {len(TS_LIST)} rows")
    conn.commit()
    conn.close()


def _create_status_db(path: str, turbines: range, cols: list, include_global: bool):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    ph = _phs(cols)
    for t_num in turbines:
        table = f"turbine_{t_num}"
        cur.execute(f'CREATE TABLE "{table}" ({col_defs})')
        rows = _gen_status_events(t_num, include_global)
        cur.executemany(f'INSERT INTO "{table}" VALUES ({ph})', rows)
        print(f"  turbine_{t_num}: {len(rows)} status events")
    conn.commit()
    conn.close()


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. kelmarsh_data_by_turbine.db
    p = os.path.join(OUT_DIR, "kelmarsh_data_by_turbine.db")
    print(f"\nCreating {os.path.basename(p)} ...")
    _create_data_db(p, range(1, 7), KELMARSH_COLS, _kelmarsh_row, "kelmarsh")

    # 2. kelmarsh_status_by_turbine.db
    p = os.path.join(OUT_DIR, "kelmarsh_status_by_turbine.db")
    print(f"\nCreating {os.path.basename(p)} ...")
    _create_status_db(p, range(1, 7), STATUS_COLS_KELMARSH, include_global=True)

    # 3. penmanshiel_data_by_turbine.db
    p = os.path.join(OUT_DIR, "penmanshiel_data_by_turbine.db")
    print(f"\nCreating {os.path.basename(p)} ...")
    _create_data_db(p, range(1, 16), PENMANSHIEL_COLS, _penmanshiel_row, "penmanshiel")

    # 4. penmanshiel_status_by_turbine.db
    p = os.path.join(OUT_DIR, "penmanshiel_status_by_turbine.db")
    print(f"\nCreating {os.path.basename(p)} ...")
    _create_status_db(p, range(1, 16), STATUS_COLS_PENMANSHIEL, include_global=False)

    print("\nDone. Files in", OUT_DIR)
    for f in sorted(os.listdir(OUT_DIR)):
        fp = os.path.join(OUT_DIR, f)
        if os.path.isfile(fp):
            print(f"  {f:45s}  {os.path.getsize(fp) / 1024:.0f} KB")

