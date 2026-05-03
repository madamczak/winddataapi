"""
Find all summary files where:
  - Rotor speed mean is within 15 ± 0.2 RPM  (14.8 – 15.2)
  - Rotor speed std is below 0.05 RPM

Outputs a sorted list of matching files to rated_rotor_hours.txt
"""
import glob
import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'crawler', 'output')
RESULT_FILE = os.path.join(os.path.dirname(__file__), '..', 'rated_rotor_hours.txt')

WIND_FIELD = 'Wind speed (m/s)'
POWER_FIELD = 'Power (kW)'
ROTOR_FIELD = 'Rotor speed (RPM)'
TARGET = 15.0
TOLERANCE = 0.2
MAX_STD = 0.05


def main():
    pattern = os.path.join(OUTPUT_DIR, '**', '*_summary.json')
    files = sorted(glob.glob(pattern, recursive=True))

    matches = []

    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                record = json.load(fh)
        except Exception:
            continue

        if record.get('data_missing') or record.get('fetch_error'):
            continue

        stats = record.get('stats', {})
        rotor = stats.get(ROTOR_FIELD)
        if not rotor:
            continue

        mean = rotor.get('mean')
        std = rotor.get('std')

        if mean is None or std is None:
            continue

        if abs(mean - TARGET) <= TOLERANCE + 1e-9 and std < MAX_STD:
            farm = record.get('farm', '?')
            turbine = record.get('turbine', '?')
            hour_start = record.get('hour_start', '?')
            wind = stats.get(WIND_FIELD, {})
            power = stats.get(POWER_FIELD, {})
            matches.append({
                'file': os.path.relpath(f, os.path.join(os.path.dirname(__file__), '..')),
                'farm': farm,
                'turbine': turbine,
                'hour_start': hour_start,
                'wind_mean': wind.get('mean'),
                'wind_std': wind.get('std'),
                'power_mean': power.get('mean'),
                'power_std': power.get('std'),
                'rotor_mean': mean,
                'rotor_std': std,
            })

    matches.sort(key=lambda x: (x['farm'], x['turbine'], x['hour_start']))

    with open(RESULT_FILE, 'w', encoding='utf-8') as out:
        out.write(f"Rated rotor hours: mean ∈ [{TARGET - TOLERANCE:.1f}, {TARGET + TOLERANCE:.1f}] RPM  |  std < {MAX_STD} RPM\n")
        out.write(f"Total matches: {len(matches)}\n")
        out.write("=" * 120 + "\n")
        out.write(f"{'Hour start':<22} {'Farm':<12} {'Turbine':<12} {'Wind m/s':>10} {'Wind std':>10} {'Power kW':>10} {'Pwr std':>9} {'Rotor RPM':>10} {'Rot std':>9}  File\n")
        out.write("-" * 120 + "\n")
        for m in matches:
            w  = f"{m['wind_mean']:>10.4f}"  if m['wind_mean']  is not None else f"{'?':>10}"
            ws = f"{m['wind_std']:>10.4f}"   if m['wind_std']   is not None else f"{'?':>10}"
            p  = f"{m['power_mean']:>10.2f}" if m['power_mean'] is not None else f"{'?':>10}"
            ps = f"{m['power_std']:>9.2f}"   if m['power_std']  is not None else f"{'?':>9}"
            out.write(
                f"{m['hour_start']:<22} {m['farm']:<12} {m['turbine']:<12} "
                f"{w} {ws} {p} {ps} "
                f"{m['rotor_mean']:>10.4f} {m['rotor_std']:>9.4f}  {m['file']}\n"
            )

    print(f"Found {len(matches)} matching hours.")
    print(f"Results saved to: {RESULT_FILE}")


if __name__ == '__main__':
    main()

