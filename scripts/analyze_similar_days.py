"""
Analyze summary files to find the most similar hours across years
based on wind speed, rotor speed, and temperature.
Then compare power output to see if it decreases over the years.
Outputs an HTML report.
"""
import glob
import json
import os
import math
from collections import defaultdict
from itertools import combinations

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'crawler', 'output')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'similar_days_report.html')

# Fields used for similarity matching
WIND_FIELD = 'Wind speed (m/s)'
ROTOR_FIELD = 'Rotor speed (RPM)'
TEMP_FIELD = 'Nacelle ambient temperature (\u00b0C)'
POWER_FIELD = 'Power (kW)'


def load_summaries():
    pattern = os.path.join(OUTPUT_DIR, '**', '*_summary.json')
    files = glob.glob(pattern, recursive=True)
    records = []
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception:
            continue
        if data.get('data_missing') or data.get('fetch_error'):
            continue
        stats = data.get('stats', {})
        if not stats:
            continue
        # Require all key fields
        if not all(k in stats for k in [WIND_FIELD, POWER_FIELD]):
            continue

        # Parse hour_start -> year, month-day, hour
        hour_start = data.get('hour_start', '')
        if not hour_start:
            continue
        try:
            dt_parts = hour_start.split(' ')
            date_part = dt_parts[0]  # YYYY-MM-DD
            time_part = dt_parts[1]  # HH:MM:SS
            year = int(date_part.split('-')[0])
            month_day = '-'.join(date_part.split('-')[1:])  # MM-DD
            hour = int(time_part.split(':')[0])
        except Exception:
            continue

        rec = {
            'file': f,
            'farm': data.get('farm', ''),
            'turbine': data.get('turbine', ''),
            'year': year,
            'month_day': month_day,
            'hour': hour,
            'hour_start': hour_start,
            'wind_mean': stats.get(WIND_FIELD, {}).get('mean'),
            'rotor_mean': stats.get(ROTOR_FIELD, {}).get('mean'),
            'temp_mean': stats.get(TEMP_FIELD, {}).get('mean'),
            'power_mean': stats.get(POWER_FIELD, {}).get('mean'),
            'power_std': stats.get(POWER_FIELD, {}).get('std'),
        }
        # Filter out None for key comparison fields
        if rec['wind_mean'] is None or rec['power_mean'] is None:
            continue
        records.append(rec)
    return records


def similarity_score(r1, r2):
    """Lower is more similar. Uses normalized euclidean distance on wind, rotor, temp."""
    diffs = []
    # Wind speed difference (scale ~0-30 m/s)
    diffs.append((r1['wind_mean'] - r2['wind_mean']) / 10.0)
    # Rotor speed difference (scale ~0-20 RPM)
    if r1['rotor_mean'] is not None and r2['rotor_mean'] is not None:
        diffs.append((r1['rotor_mean'] - r2['rotor_mean']) / 10.0)
    # Temperature difference (scale ~-10 to 40 C)
    if r1['temp_mean'] is not None and r2['temp_mean'] is not None:
        diffs.append((r1['temp_mean'] - r2['temp_mean']) / 20.0)
    return math.sqrt(sum(d * d for d in diffs))


def find_similar_groups(records, top_n=20):
    """
    Group records by (farm, turbine, month_day, hour).
    For each group with data from multiple years, compute pairwise similarity.
    Return top_n groups with lowest average pairwise similarity (most similar conditions).
    """
    groups = defaultdict(list)
    for r in records:
        key = (r['farm'], r['turbine'], r['month_day'], r['hour'])
        groups[key].append(r)

    results = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # Compute all pairwise similarity scores
        pairs = list(combinations(members, 2))
        scores = [similarity_score(a, b) for a, b in pairs]
        avg_score = sum(scores) / len(scores)
        results.append({
            'key': key,
            'members': sorted(members, key=lambda x: x['year']),
            'avg_similarity': avg_score,
            'pair_count': len(pairs),
        })

    results.sort(key=lambda x: x['avg_similarity'])
    return results[:top_n]


def power_trend(members):
    """Simple linear regression of power_mean vs year."""
    n = len(members)
    if n < 2:
        return None, None
    xs = [m['year'] for m in members]
    ys = [m['power_mean'] for m in members]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0, y_mean
    slope = num / den
    intercept = y_mean - slope * x_mean
    return slope, intercept


def render_html(similar_groups, all_records):
    # Summary stats
    total_files = len(all_records)
    farms = sorted(set(r['farm'] for r in all_records))
    years = sorted(set(r['year'] for r in all_records))

    rows_html = ''
    trend_summary = []

    for idx, g in enumerate(similar_groups):
        farm, turbine, month_day, hour = g['key']
        members = g['members']
        slope, intercept = power_trend(members)

        trend_dir = ''
        trend_color = '#333'
        if slope is not None:
            if slope < -5:
                trend_dir = f'&#9660; DECREASING ({slope:+.1f} kW/yr)'
                trend_color = '#c0392b'
            elif slope > 5:
                trend_dir = f'&#9650; INCREASING ({slope:+.1f} kW/yr)'
                trend_color = '#27ae60'
            else:
                trend_dir = f'&#8596; STABLE ({slope:+.1f} kW/yr)'
                trend_color = '#2980b9'
            trend_summary.append({'label': f'{farm}/{turbine} {month_day} {hour:02d}h', 'slope': slope})

        member_rows = ''
        for m in members:
            power_disp = f"{m['power_mean']:.1f} kW" if m['power_mean'] else 'N/A'
            wind_disp = f"{m['wind_mean']:.2f} m/s" if m['wind_mean'] else 'N/A'
            rotor_disp = f"{m['rotor_mean']:.2f} RPM" if m['rotor_mean'] else 'N/A'
            temp_disp = f"{m['temp_mean']:.1f} °C" if m['temp_mean'] else 'N/A'
            member_rows += f"""
            <tr>
                <td>{m['year']}</td>
                <td>{m['hour_start']}</td>
                <td>{wind_disp}</td>
                <td>{rotor_disp}</td>
                <td>{temp_disp}</td>
                <td><strong>{power_disp}</strong></td>
            </tr>"""

        rows_html += f"""
        <div class="group" id="group-{idx}">
            <h3>#{idx+1} &mdash; {farm} / {turbine} &mdash; {month_day} hour {hour:02d}:00
                <span class="badge">similarity score: {g['avg_similarity']:.4f}</span>
            </h3>
            <p>Years with data: {', '.join(str(m['year']) for m in members)} &nbsp;|&nbsp; Pairs compared: {g['pair_count']}</p>
            <p>Power trend: <span style="color:{trend_color};font-weight:bold">{trend_dir}</span></p>
            <table>
                <thead>
                    <tr>
                        <th>Year</th><th>Hour Start</th><th>Wind Speed</th>
                        <th>Rotor Speed</th><th>Nacelle Temp</th><th>Power (kW)</th>
                    </tr>
                </thead>
                <tbody>{member_rows}</tbody>
            </table>
        </div>"""

    # Trend summary bar chart data
    trend_summary.sort(key=lambda x: x['slope'])
    bar_labels = json.dumps([t['label'] for t in trend_summary])
    bar_values = json.dumps([round(t['slope'], 2) for t in trend_summary])
    bar_colors = json.dumps(['#c0392b' if t['slope'] < -5 else ('#27ae60' if t['slope'] > 5 else '#2980b9') for t in trend_summary])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Wind Turbine Similar Days Analysis</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f9; color: #222; margin: 0; padding: 0; }}
  header {{ background: #1a2540; color: white; padding: 24px 40px; }}
  header h1 {{ margin: 0; font-size: 1.8em; }}
  header p {{ margin: 6px 0 0; opacity: 0.75; }}
  .container {{ max-width: 1200px; margin: 30px auto; padding: 0 20px; }}
  .stats-bar {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 30px; }}
  .stat-box {{ background: white; border-radius: 8px; padding: 16px 28px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); flex: 1; min-width: 140px; }}
  .stat-box .val {{ font-size: 2em; font-weight: bold; color: #1a2540; }}
  .stat-box .lbl {{ font-size: 0.85em; color: #666; }}
  .chart-wrap {{ background: white; border-radius: 8px; padding: 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); margin-bottom: 30px; }}
  .group {{ background: white; border-radius: 8px; padding: 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); margin-bottom: 20px; }}
  .group h3 {{ margin-top: 0; color: #1a2540; }}
  .badge {{ background: #e8edf5; color: #555; font-size: 0.75em; padding: 3px 10px; border-radius: 12px; font-weight: normal; margin-left: 10px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.93em; }}
  th {{ background: #1a2540; color: white; padding: 8px 12px; text-align: left; }}
  td {{ padding: 7px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f0f4ff; }}
  h2 {{ color: #1a2540; border-bottom: 2px solid #1a2540; padding-bottom: 6px; }}
</style>
</head>
<body>
<header>
  <h1>&#127744; Wind Turbine – Similar Days Power Analysis</h1>
  <p>Comparing hours with similar wind speed, rotor speed &amp; temperature across different years to detect power output degradation.</p>
</header>
<div class="container">
  <div class="stats-bar">
    <div class="stat-box"><div class="val">{total_files}</div><div class="lbl">Summary files loaded</div></div>
    <div class="stat-box"><div class="val">{len(farms)}</div><div class="lbl">Wind farms</div></div>
    <div class="stat-box"><div class="val">{len(years)}</div><div class="lbl">Years covered</div></div>
    <div class="stat-box"><div class="val">{years[0] if years else '?'}–{years[-1] if years else '?'}</div><div class="lbl">Year range</div></div>
    <div class="stat-box"><div class="val">{len(similar_groups)}</div><div class="lbl">Similar groups found</div></div>
  </div>

  <h2>Power Trend Overview (kW/year slope)</h2>
  <div class="chart-wrap">
    <canvas id="trendChart" height="80"></canvas>
  </div>

  <h2>Top {len(similar_groups)} Most Similar Hour-Groups Across Years</h2>
  <p style="color:#555;">Groups are sorted by similarity score (lower = more similar conditions). Each group shows the same calendar hour from different years.</p>
  {rows_html}
</div>

<script>
const ctx = document.getElementById('trendChart').getContext('2d');
new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: {bar_labels},
    datasets: [{{
      label: 'Power slope (kW/year)',
      data: {bar_values},
      backgroundColor: {bar_colors},
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.x.toFixed(2) + ' kW/yr' }} }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: 'kW per year (negative = decreasing power)' }} }},
      y: {{ ticks: {{ font: {{ size: 11 }} }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def main():
    print("Loading summary files...")
    records = load_summaries()
    print(f"Loaded {len(records)} valid summary records.")

    if not records:
        print("No records found. Check the output directory path.")
        return

    print("Finding most similar groups across years...")
    similar = find_similar_groups(records, top_n=30)
    print(f"Found {len(similar)} similar groups.")

    html = render_html(similar, records)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Report written to: {REPORT_PATH}")


if __name__ == '__main__':
    main()

