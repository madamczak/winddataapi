"""
Generate an HTML report for January 1st data across all years.
Shows all 24 hours for kelmarsh/turbine_2, comparing each hour across years.
"""
import glob
import json
import math
import os
from collections import defaultdict
from itertools import combinations

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'crawler', 'output')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'jan1_report.html')

WIND_FIELD = 'Wind speed (m/s)'
ROTOR_FIELD = 'Rotor speed (RPM)'
TEMP_FIELD = 'Nacelle ambient temperature (\u00b0C)'
POWER_FIELD = 'Power (kW)'


def load_jan1_summaries():
    pattern = os.path.join(OUTPUT_DIR, '**', '*-01-01_*_summary.json')
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
        if WIND_FIELD not in stats or POWER_FIELD not in stats:
            continue

        hour_start = data.get('hour_start', '')
        if not hour_start:
            continue
        try:
            date_part, time_part = hour_start.split(' ')
            year = int(date_part.split('-')[0])
            hour = int(time_part.split(':')[0])
        except Exception:
            continue

        records.append({
            'file': f,
            'farm': data.get('farm', ''),
            'turbine': data.get('turbine', ''),
            'year': year,
            'hour': hour,
            'hour_start': hour_start,
            'wind_mean': stats.get(WIND_FIELD, {}).get('mean'),
            'rotor_mean': stats.get(ROTOR_FIELD, {}).get('mean'),
            'temp_mean': stats.get(TEMP_FIELD, {}).get('mean'),
            'power_mean': stats.get(POWER_FIELD, {}).get('mean'),
            'power_std': stats.get(POWER_FIELD, {}).get('std'),
            'status_count': data.get('status_count', 0),
            'statuses': data.get('statuses', []),
        })
    return records


def similarity_score(r1, r2):
    diffs = [(r1['wind_mean'] - r2['wind_mean']) / 10.0]
    if r1['rotor_mean'] is not None and r2['rotor_mean'] is not None:
        diffs.append((r1['rotor_mean'] - r2['rotor_mean']) / 10.0)
    if r1['temp_mean'] is not None and r2['temp_mean'] is not None:
        diffs.append((r1['temp_mean'] - r2['temp_mean']) / 20.0)
    return math.sqrt(sum(d * d for d in diffs))


def power_trend(members):
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
    return num / den, y_mean - (num / den) * x_mean


def render_html(records):
    farms = sorted(set(r['farm'] for r in records))
    years = sorted(set(r['year'] for r in records))
    total_files = len(records)

    # Group by (farm, turbine, hour)
    groups = defaultdict(list)
    for r in records:
        groups[(r['farm'], r['turbine'], r['hour'])].append(r)

    # Sort groups by hour
    sorted_keys = sorted(groups.keys(), key=lambda k: k[2])

    # Build per-hour chart data: avg power per year
    # We'll collect for the chart section
    chart_labels = []
    chart_slope_data = []
    chart_colors = []

    hour_sections_html = ''
    for idx, key in enumerate(sorted_keys):
        farm, turbine, hour = key
        members = sorted(groups[key], key=lambda x: x['year'])
        slope, _ = power_trend(members)

        if slope is not None:
            if slope < -5:
                trend_dir = f'&#9660; DECREASING ({slope:+.1f} kW/yr)'
                trend_color = '#c0392b'
                bar_color = '#c0392b'
            elif slope > 5:
                trend_dir = f'&#9650; INCREASING ({slope:+.1f} kW/yr)'
                trend_color = '#27ae60'
                bar_color = '#27ae60'
            else:
                trend_dir = f'&#8596; STABLE ({slope:+.1f} kW/yr)'
                trend_color = '#2980b9'
                bar_color = '#2980b9'
        else:
            trend_dir = 'N/A'
            trend_color = '#999'
            bar_color = '#999'

        chart_labels.append(f'{hour:02d}:00')
        chart_slope_data.append(round(slope, 2) if slope is not None else 0)
        chart_colors.append(bar_color)

        # Pairwise similarity
        pairs = list(combinations(members, 2))
        avg_sim = sum(similarity_score(a, b) for a, b in pairs) / len(pairs) if pairs else 0

        member_rows = ''
        for m in members:
            wind_d = f"{m['wind_mean']:.2f} m/s" if m['wind_mean'] is not None else 'N/A'
            rotor_d = f"{m['rotor_mean']:.2f} RPM" if m['rotor_mean'] is not None else 'N/A'
            temp_d = f"{m['temp_mean']:.1f} °C" if m['temp_mean'] is not None else 'N/A'
            power_d = f"{m['power_mean']:.1f} kW" if m['power_mean'] is not None else 'N/A'
            status_d = str(m['status_count'])
            member_rows += f"""
            <tr>
                <td>{m['year']}</td>
                <td>{m['hour_start']}</td>
                <td>{wind_d}</td>
                <td>{rotor_d}</td>
                <td>{temp_d}</td>
                <td><strong>{power_d}</strong></td>
                <td>{status_d}</td>
            </tr>"""

        # Per-hour power chart data
        pw_labels = json.dumps([str(m['year']) for m in members])
        pw_data = json.dumps([round(m['power_mean'], 1) if m['power_mean'] is not None else 0 for m in members])

        hour_sections_html += f"""
        <div class="group" id="hour-{hour:02d}">
            <h3>&#128336; {hour:02d}:00 &mdash; {farm} / {turbine}
                <span class="badge">avg similarity: {avg_sim:.4f}</span>
            </h3>
            <p>Years with data: {', '.join(str(m['year']) for m in members)} &nbsp;|&nbsp;
               Pairs: {len(pairs)}</p>
            <p>Power trend: <span style="color:{trend_color};font-weight:bold">{trend_dir}</span></p>
            <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;">
              <div style="flex:2;min-width:300px;">
                <table>
                  <thead>
                    <tr>
                      <th>Year</th><th>Hour Start</th><th>Wind Speed</th>
                      <th>Rotor Speed</th><th>Nacelle Temp</th><th>Power (kW)</th><th>Statuses</th>
                    </tr>
                  </thead>
                  <tbody>{member_rows}</tbody>
                </table>
              </div>
              <div style="flex:1;min-width:240px;max-width:360px;">
                <canvas id="pwchart-{hour:02d}" height="160"></canvas>
              </div>
            </div>
        </div>
        <script>
        (function(){{
          var ctx = document.getElementById('pwchart-{hour:02d}').getContext('2d');
          new Chart(ctx, {{
            type: 'bar',
            data: {{
              labels: {pw_labels},
              datasets: [{{
                label: 'Power (kW)',
                data: {pw_data},
                backgroundColor: '{bar_color}88',
                borderColor: '{bar_color}',
                borderWidth: 1,
                borderRadius: 3,
              }}]
            }},
            options: {{
              plugins: {{
                legend: {{ display: false }},
                tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.y.toFixed(1) + ' kW' }} }}
              }},
              scales: {{
                y: {{ title: {{ display: true, text: 'kW' }}, beginAtZero: false }}
              }}
            }}
          }});
        }})();
        </script>"""

    chart_labels_json = json.dumps(chart_labels)
    chart_slope_json = json.dumps(chart_slope_data)
    chart_colors_json = json.dumps(chart_colors)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>January 1st – Wind Turbine Report</title>
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
  .toc {{ background: white; border-radius: 8px; padding: 16px 24px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); margin-bottom: 30px; }}
  .toc a {{ display: inline-block; margin: 4px 6px; padding: 4px 12px; background: #e8edf5; border-radius: 14px; color: #1a2540; text-decoration: none; font-size: 0.9em; }}
  .toc a:hover {{ background: #1a2540; color: white; }}
</style>
</head>
<body>
<header>
  <h1>&#127751; January 1st – Wind Turbine Power Report</h1>
  <p>kelmarsh / turbine_2 &mdash; All 24 hours of January 1st compared across years ({min(years)}–{max(years)})</p>
</header>
<div class="container">

  <div class="stats-bar">
    <div class="stat-box"><div class="val">{total_files}</div><div class="lbl">Summary files loaded</div></div>
    <div class="stat-box"><div class="val">{len(farms)}</div><div class="lbl">Wind farm(s)</div></div>
    <div class="stat-box"><div class="val">{len(years)}</div><div class="lbl">Years covered</div></div>
    <div class="stat-box"><div class="val">{min(years)}–{max(years)}</div><div class="lbl">Year range</div></div>
    <div class="stat-box"><div class="val">{len(sorted_keys)}</div><div class="lbl">Hour slots</div></div>
  </div>

  <h2>Power Trend Overview (kW/year slope per hour)</h2>
  <div class="chart-wrap">
    <canvas id="trendChart" height="90"></canvas>
  </div>

  <div class="toc">
    <strong>Jump to hour:</strong>
    {''.join(f'<a href="#hour-{h:02d}">{h:02d}:00</a>' for _, _, h in sorted_keys)}
  </div>

  <h2>All 24 Hours – Year-over-Year Comparison</h2>
  {hour_sections_html}

</div>
<script>
const ctx = document.getElementById('trendChart').getContext('2d');
new Chart(ctx, {{
  type: 'bar',
  data: {{
    labels: {chart_labels_json},
    datasets: [{{
      label: 'Power slope (kW/year)',
      data: {chart_slope_json},
      backgroundColor: {chart_colors_json},
      borderRadius: 4,
    }}]
  }},
  options: {{
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.y.toFixed(2) + ' kW/yr' }} }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Hour of day' }} }},
      y: {{ title: {{ display: true, text: 'kW per year (negative = decreasing)' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def main():
    print("Loading January 1st summaries ...")
    records = load_jan1_summaries()
    print(f"  Loaded {len(records)} records from {len(set(r['year'] for r in records))} years")

    html = render_html(records)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Report saved to: {REPORT_PATH}")


if __name__ == '__main__':
    main()

