"""
Inject Charts tab into similar_days_report.html using rated_rotor_hours.txt data.
Safe to run multiple times — replaces dataset content if already present.
"""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), '..')
TXT_FILE = os.path.join(ROOT, 'rated_rotor_hours.txt')
HTML_FILE = os.path.join(ROOT, 'similar_days_report.html')

YEAR_COLORS = {
    2016: '#e74c3c', 2017: '#e67e22', 2018: '#f1c40f',
    2019: '#2ecc71', 2020: '#1abc9c', 2021: '#3498db',
    2022: '#9b59b6', 2023: '#e91e63',
}


def parse_txt(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines[5:]:
        line = line.rstrip('\n')
        if not line.strip() or line.startswith('-') or line.startswith('='):
            continue
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            hour_start = parts[0] + ' ' + parts[1]
            wind_mean  = float(parts[4])
            power_mean = float(parts[6])
            rotor_mean = float(parts[8])
        except Exception:
            continue
        year = int(hour_start[:4])
        rows.append({'ts': hour_start, 'year': year,
                     'wind': wind_mean, 'power': power_mean, 'rotor': rotor_mean})
    return rows


def build_datasets(rows, field):
    by_year = {}
    for r in rows:
        by_year.setdefault(r['year'], []).append({'x': r['ts'], 'y': r[field]})
    return [
        {'label': str(y), 'data': pts,
         'backgroundColor': YEAR_COLORS.get(y, '#999'),
         'borderColor': YEAR_COLORS.get(y, '#999'),
         'pointRadius': 3, 'pointHoverRadius': 5}
        for y, pts in sorted(by_year.items())
    ]


CHARTS_TAB_HTML = """
<!-- ===== CHARTS TAB ===== -->
<div class="tab-panel" id="tab-charts" style="display:none">
  <div class="chart-wrap">
    <h2 style="margin-top:0">Rotor Speed at Rated Conditions (RPM)</h2>
    <p style="color:#555;margin-top:-10px">
      Hours where rotor speed mean &isin; [14.8&ndash;15.2] RPM and std &lt; 0.05,
      plotted over time, coloured by year.
    </p>
    <canvas id="rotorChart" height="70"></canvas>
  </div>
  <div class="chart-wrap">
    <h2 style="margin-top:0">Power Output at Rated Rotor Speed (kW)</h2>
    <p style="color:#555;margin-top:-10px">
      Same filtered hours &mdash; power output for each year.
    </p>
    <canvas id="powerChart" height="70"></canvas>
  </div>
</div>"""

CHARTS_SCRIPT_TMPL = """<script>
/* RATED_ROTOR_CHARTS */
(function() {
  const rotorDatasets = ROTOR_JSON;
  const powerDatasets = POWER_JSON;

  function makeChart(id, datasets, yLabel, unit) {
    const ctx = document.getElementById(id).getContext('2d');
    new Chart(ctx, {
      type: 'scatter',
      data: { datasets },
      options: {
        parsing: false,
        animation: false,
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(3) + ' ' + unit + '  (' + c.raw.x + ')'
            }
          }
        },
        scales: {
          x: {
            type: 'time',
            time: { unit: 'month', tooltipFormat: 'yyyy-MM-dd HH:mm' },
            title: { display: true, text: 'Date' },
            ticks: { maxTicksLimit: 16 }
          },
          y: { title: { display: true, text: yLabel } }
        }
      }
    });
  }

  makeChart('rotorChart', rotorDatasets, 'Rotor Speed (RPM)', 'RPM');
  makeChart('powerChart', powerDatasets, 'Power (kW)', 'kW');
})();
</script>"""

TAB_NAV_HTML = """
<div class="tab-nav">
  <button class="tab-nav-btn active" onclick="switchMainTab('tab-analysis',this)">&#128202; Analysis</button>
  <button class="tab-nav-btn" onclick="switchMainTab('tab-charts',this)">&#128200; Charts</button>
</div>"""

TAB_NAV_CSS = """
  .tab-nav { display:flex; gap:8px; margin-bottom:0; background:white;
             padding:12px 20px; border-radius:8px 8px 0 0;
             box-shadow:0 2px 6px rgba(0,0,0,0.08); }
  .tab-nav-btn { padding:8px 22px; border:none; border-radius:20px; cursor:pointer;
                 background:#e8edf5; color:#333; font-size:0.92em; font-weight:600;
                 transition:background 0.15s; }
  .tab-nav-btn:hover { background:#c5d0e8; }
  .tab-nav-btn.active { background:#1a2540; color:white; }
  .tab-panel { background:transparent; }"""

TAB_SWITCH_JS = """<script>
function switchMainTab(id, btn) {
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.tab-nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).style.display = 'block';
  btn.classList.add('active');
}
</script>"""

ADAPTER_TAG = '<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>'


def main():
    print('Parsing rated_rotor_hours.txt ...')
    rows = parse_txt(TXT_FILE)
    print(f'  {len(rows)} data points loaded')

    rotor_json = json.dumps(build_datasets(rows, 'rotor'))
    power_json = json.dumps(build_datasets(rows, 'power'))

    charts_script = CHARTS_SCRIPT_TMPL.replace('ROTOR_JSON', rotor_json).replace('POWER_JSON', power_json)

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    already_patched = 'tab-charts' in html

    # ── Already patched: replace dataset JSON in-place ───────────────────────
    if already_patched:
        html = re.sub(
            r'const rotorDatasets = \[.*?\];',
            f'const rotorDatasets = {rotor_json};',
            html, flags=re.DOTALL
        )
        html = re.sub(
            r'const powerDatasets = \[.*?\];',
            f'const powerDatasets = {power_json};',
            html, flags=re.DOTALL
        )
        with open(HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'Datasets updated in: {HTML_FILE}')
        return

    # ── Fresh patch ───────────────────────────────────────────────────────────

    # 1. Add date-fns adapter AFTER chart.js
    if 'chartjs-adapter' not in html:
        html = html.replace(
            '</script>\n<style>',
            '</script>\n' + ADAPTER_TAG + '\n<style>',
            1
        )

    # 2. Inject tab CSS into <style>
    if '.tab-nav' not in html:
        html = html.replace('</style>', TAB_NAV_CSS + '\n</style>', 1)

    # 3. Insert tab-nav and open #tab-analysis wrapper inside .container
    html = html.replace(
        '<div class="container">',
        TAB_NAV_HTML + '\n<div class="container">\n<div class="tab-panel" id="tab-analysis">',
        1
    )

    # 4. Close #tab-analysis at the last </div>, inject charts tab, close container
    last_div = html.rfind('</div>')
    html = (
        html[:last_div]
        + '</div><!-- /tab-analysis -->\n'
        + CHARTS_TAB_HTML + '\n'
        + '</div><!-- /container -->\n'
        + html[last_div + len('</div>'):]
    )

    # 5. Inject charts script + tab-switch JS before </body>
    html = html.replace('</body>', charts_script + '\n' + TAB_SWITCH_JS + '\n</body>', 1)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Patched: {HTML_FILE}')


if __name__ == '__main__':
    main()

