"""
Generate an HTML report visualizing turbine data from summary files.
Each month is a separate tab. Within each tab, you can pick a day and a field.
Table rows = hours (00:00 – 23:00), columns = years.

Usage:
    python monthly_wind_report.py [--farm kelmarsh] [--turbine turbine_2]
"""
import argparse
import glob
import json
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'crawler', 'output')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'monthly_wind_report.html')

WIND_FIELD = 'Wind speed (m/s)'

MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

# (field_key_in_json, label, unit, color_max, low_std_threshold)
FIELDS = [
    ('w', 'Wind Speed',    'm/s',  20.0,   0.5),
    ('p', 'Power',         'kW',   2500.0, 50.0),
    ('r', 'Rotor Speed',   'RPM',  20.0,   0.5),
    ('g', 'Generator RPM', 'RPM',  2000.0, 20.0),
]

# Mapping from compact key -> full stats field name
FIELD_STAT_KEYS = {
    'w': 'Wind speed (m/s)',
    'p': 'Power (kW)',
    'r': 'Rotor speed (RPM)',
    'g': 'Generator RPM (RPM)',
}


def load_summaries(farm: str, turbine: str):
    """
    Load all summary files. Returns:
      data[month][day][year][hour] = {w:[mean,std], p:[mean,std], r:[mean,std], g:[mean,std]}
    All keys are integers except the top-level dict keys remain ints.
    """
    pattern = os.path.join(OUTPUT_DIR, farm, turbine, '*_summary.json')
    files = glob.glob(pattern)

    data = {}  # nested: month -> day -> year -> hour -> {field: [mean, std]}
    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                record = json.load(fh)
        except Exception:
            continue

        if record.get('data_missing') or record.get('fetch_error'):
            continue

        stats = record.get('stats', {})
        if not stats or WIND_FIELD not in stats:
            continue

        hour_start = record.get('hour_start', '')
        if not hour_start:
            continue

        try:
            date_part, time_part = hour_start.split(' ')
            year, month, day = map(int, date_part.split('-'))
            hour = int(time_part.split(':')[0])
        except Exception:
            continue

        cell = {}
        for fkey, fname in FIELD_STAT_KEYS.items():
            fs = stats.get(fname)
            if fs:
                cell[fkey] = [round(fs.get('mean', 0), 4), round(fs.get('std', 0), 4)]

        data.setdefault(month, {}).setdefault(day, {}).setdefault(year, {})[hour] = cell

    return data


def render_html(farm: str, turbine: str, data: dict):
    months_with_data = sorted(data.keys())
    all_years = sorted({y for m in data.values() for d in m.values() for y in d.keys()})

    # Build month/day nav HTML (no pre-rendered tables — JS handles rendering)
    tabs_nav = ''
    tabs_content = ''

    for month in months_with_data:
        month_name = MONTH_NAMES[month - 1]
        month_id = f'month-{month:02d}'
        days = sorted(data[month].keys())

        day_btns = ''.join(
            f'<button class="day-btn" onclick="switchDay(\'{month_id}\',{day})" '
            f'id="btn-{month_id}-d{day:02d}">{day:02d}</button>\n'
            for day in days
        )

        tabs_nav += (
            f'<button class="tab-btn" onclick="switchTab(\'{month_id}\')" '
            f'id="btn-{month_id}">{month_name}</button>\n'
        )
        tabs_content += f"""
        <div class="tab-panel" id="{month_id}" style="display:none">
          <h3 id="heading-{month_id}">{month_name}</h3>
          <div class="days-nav" id="daynav-{month_id}">{day_btns}</div>
          <div class="field-nav" id="fieldnav-{month_id}">
            {''.join(
                f'<button class="field-btn{" active" if i==0 else ""}" '
                f'onclick="switchField(\'{month_id}\',\'{fkey}\')" '
                f'id="btn-{month_id}-f{fkey}">{label} ({unit})</button>'
                for i, (fkey, label, unit, _, _) in enumerate(FIELDS)
            )}
          </div>
          <p class="sub" id="sub-{month_id}">
            Farm: <strong>{farm}</strong> | Turbine: <strong>{turbine}</strong>
          </p>
          <div class="filter-bar" id="filterbar-{month_id}">
            <label>Filter by:
              <select id="ffield-{month_id}">
                {''.join(f'<option value="{fkey}"{"  selected" if fkey=="r" else ""}>{label} ({unit})</option>' for fkey, label, unit, _, _ in FIELDS)}
              </select>
            </label>
            <label>= <input type="number" step="any" id="fval-{month_id}" value="15" style="width:80px"></label>
            <label>± <input type="number" step="any" id="ftol-{month_id}" value="0.2" style="width:60px" min="0"></label>
            <button onclick="applyFilter('{month_id}')">Apply</button>
            <button onclick="clearFilter('{month_id}')">Show all</button>
            <span id="finfo-{month_id}" style="font-size:0.82em;color:#888;margin-left:8px"></span>
          </div>
          <div id="table-area-{month_id}"></div>
        </div>"""

    first_month_id = f'month-{months_with_data[0]:02d}' if months_with_data else ''

    # Compact JSON data embed: DATA[month][day][year][hour] = {w,p,r,g}
    # Convert int keys to strings for JSON
    def to_str_keys(d):
        if isinstance(d, dict):
            return {str(k): to_str_keys(v) for k, v in d.items()}
        return d

    data_json = json.dumps(to_str_keys(data), separators=(',', ':'))

    fields_json = json.dumps([
        {'key': fkey, 'label': label, 'unit': unit, 'max': cmax, 'lowStd': lstd}
        for fkey, label, unit, cmax, lstd in FIELDS
    ])

    years_json = json.dumps(all_years)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Wind Turbine Report – {farm} / {turbine}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f3f7; color: #222; margin: 0; padding: 0; }}
  header {{ background: #1a2540; color: white; padding: 20px 40px; }}
  header h1 {{ margin: 0; font-size: 1.6em; }}
  header p {{ margin: 4px 0 0; opacity: 0.7; font-size: 0.9em; }}
  .container {{ max-width: 1500px; margin: 24px auto; padding: 0 20px; }}

  .tabs-nav {{ display: flex; flex-wrap: wrap; gap: 6px; background: white;
               padding: 14px 20px; border-radius: 8px 8px 0 0;
               box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
  .tab-btn {{ padding: 7px 16px; border: none; border-radius: 20px; cursor: pointer;
              background: #e8edf5; color: #333; font-size: 0.88em; font-weight: 500; transition: background 0.15s; }}
  .tab-btn:hover {{ background: #c5d0e8; }}
  .tab-btn.active {{ background: #1a2540; color: white; }}

  .days-nav {{ display: flex; flex-wrap: wrap; gap: 4px; padding: 10px 0 10px;
               border-bottom: 1px solid #eef0f5; margin-bottom: 10px; }}
  .day-btn {{ padding: 4px 11px; border: 1px solid #c5d0e8; border-radius: 14px; cursor: pointer;
              background: #f0f3f7; color: #444; font-size: 0.82em; font-weight: 500; transition: background 0.12s; }}
  .day-btn:hover {{ background: #d0daee; }}
  .day-btn.active {{ background: #2c3e60; color: white; border-color: #2c3e60; }}

  .field-nav {{ display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 0 14px;
                border-bottom: 2px solid #eef0f5; margin-bottom: 14px; }}
  .field-btn {{ padding: 6px 18px; border: 1px solid #b0bcd8; border-radius: 20px; cursor: pointer;
                background: #eef1f8; color: #333; font-size: 0.85em; font-weight: 500; transition: background 0.12s; }}
  .field-btn:hover {{ background: #d0daee; }}
  .field-btn.active {{ background: #e07b00; color: white; border-color: #e07b00; }}

  .tab-panel {{ background: white; border-radius: 0 0 8px 8px; padding: 24px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
  .tab-panel h3 {{ margin-top: 0; color: #1a2540; }}
  .sub {{ color: #666; font-size: 0.88em; margin: 0 0 12px; }}

  .table-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; font-size: 0.84em; min-width: 600px; table-layout: fixed; width: 100%; }}
  th {{ background: #1a2540; color: white; padding: 8px 14px; text-align: center;
        position: sticky; top: 0; white-space: nowrap; width: 90px; }}
  th.hour-col {{ background: #2c3e60; min-width: 60px; width: 60px; }}
  td {{ padding: 6px 12px; text-align: center; border-bottom: 1px solid #eee; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  td.hour-label {{ background: #f5f7fa; font-weight: 600; color: #1a2540; text-align: left;
                   position: sticky; left: 0; border-right: 2px solid #dde; width: 60px; }}
  td.no-data {{ color: #bbb; font-size: 0.85em; }}
  tr:hover td {{ filter: brightness(0.93); }}

  .legend {{ display: flex; align-items: center; gap: 6px; margin-top: 14px; flex-wrap: wrap; }}
  .leg-item {{ padding: 3px 12px; border-radius: 12px; font-size: 0.82em; }}

  .info-box {{ background: white; border-radius: 8px; padding: 16px 24px;
               box-shadow: 0 2px 6px rgba(0,0,0,0.08); margin-bottom: 16px;
               font-size: 0.9em; color: #555; }}

  .filter-bar {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                 padding: 8px 12px; background: #f5f7fa; border-radius: 6px;
                 border: 1px solid #dde; margin-bottom: 14px; font-size: 0.88em; }}
  .filter-bar input {{ padding: 3px 6px; border: 1px solid #bbb; border-radius: 4px; font-size: 0.95em; }}
  .filter-bar button {{ padding: 4px 14px; border: none; border-radius: 14px; cursor: pointer;
                        background: #1a2540; color: white; font-size: 0.85em; }}
  .filter-bar button:hover {{ background: #2c3e60; }}
</style>
</head>
<body>
<header>
  <h1>📊 Wind Turbine Report</h1>
  <p>{farm} / {turbine} &mdash; all days, all hours, all years</p>
</header>
<div class="container">
  <div class="info-box">
    Select a <strong>month</strong>, then a <strong>day</strong>, then a <strong>field</strong> to view.
    Each cell shows <strong>mean ± std</strong> for that hour across all years.
    Gold border = std below low-variability threshold. Missing data shown as <strong>–</strong>.
    Years available: <strong>{', '.join(str(y) for y in all_years)}</strong>.
  </div>
  <div class="tabs-nav">{tabs_nav}</div>
  {tabs_content}
</div>

<script>
const DATA = {data_json};
const FIELDS = {fields_json};
const ALL_YEARS = {years_json};

// current state
let curMonth = null, curDay = null, curField = FIELDS[0].key;
// filter: null = show all, otherwise {{val, tol, field}}
let curFilter = {{val: 15, tol: 0.2, field: 'r'}};

function applyFilter(monthId) {{
  const val = parseFloat(document.getElementById('fval-' + monthId).value);
  const tol = parseFloat(document.getElementById('ftol-' + monthId).value);
  const field = document.getElementById('ffield-' + monthId).value;
  if (isNaN(val) || isNaN(tol) || tol < 0) return;
  curFilter = {{val, tol, field}};
  if (curDay !== null) renderTable(monthId, curDay, curField);
}}

function clearFilter(monthId) {{
  curFilter = null;
  document.getElementById('finfo-' + monthId).textContent = '';
  if (curDay !== null) renderTable(monthId, curDay, curField);
}}

function colorCell(val, fieldCfg) {{
  const intensity = Math.min(val / fieldCfg.max, 1.0);
  const r = Math.round(30 + intensity * 200);
  const g = Math.round(100 - intensity * 60);
  const b = Math.round(200 - intensity * 170);
  return {{bg: `rgb(${{r}},${{g}},${{b}})`, fg: intensity > 0.4 ? 'white' : '#222'}};
}}

function renderTable(monthId, day, fieldKey) {{
  const mNum = parseInt(monthId.replace('month-', ''), 10);
  const fieldCfg = FIELDS.find(f => f.key === fieldKey);
  const filterFieldCfg = curFilter ? FIELDS.find(f => f.key === curFilter.field) : null;
  const monthData = DATA[mNum] || {{}};
  const dayData = monthData[day] || {{}};

  // always use ALL_YEARS so every table has the same columns
  const years = ALL_YEARS;

  let thead = '<th class="hour-col">Hour</th>' + years.map(y => `<th>${{y}}</th>`).join('');
  let tbody = '';
  let matchCount = 0;
  for (let h = 0; h < 24; h++) {{
    let cells = `<td class="hour-label">${{String(h).padStart(2,'0')}}:00</td>`;
    for (const y of years) {{
      const entry = (dayData[y] || {{}})[h];
      const fdata = entry ? entry[fieldKey] : null;
      if (fdata && fdata[0] !== null && fdata[0] !== undefined) {{
        const mean = fdata[0], std = fdata[1];
        // check filter on the filter field (not the displayed field)
        let inRange = true;
        if (curFilter) {{
          const filterFdata = entry ? entry[curFilter.field] : null;
          const filterMean = filterFdata ? filterFdata[0] : null;
          inRange = filterMean !== null && Math.abs(filterMean - curFilter.val) <= curFilter.tol + 1e-9;
        }}
        // additionally exclude if wind speed std > 1
        if (inRange) {{
          const windFdata = entry ? entry['w'] : null;
          const windStd = windFdata ? windFdata[1] : null;
          if (windStd !== null && windStd > 1) inRange = false;
        }}
        if (inRange) matchCount++;
        const {{bg, fg}} = inRange ? colorCell(mean, fieldCfg) : {{bg:'#f8f8f8', fg:'#aaa'}};
        const lowStd = inRange && std !== null && std < fieldCfg.lowStd;
        const border = lowStd ? 'box-shadow:inset 0 0 0 3px rgba(255,255,255,0.9);outline:2px solid #FFD700;' : '';
        const stdStr = inRange && std !== null ? ` <span style="font-size:0.78em;opacity:0.85">±${{std.toFixed(2)}}</span>` : '';
        const displayVal = inRange ? `${{mean.toFixed(2)}}${{stdStr}}` : `<span style="font-size:0.8em">${{mean.toFixed(1)}}</span>`;
        cells += `<td style="background:${{bg}};color:${{fg}};${{border}}" title="${{y}}-${{String(mNum).padStart(2,'0')}}-${{String(day).padStart(2,'0')}} ${{String(h).padStart(2,'0')}}:00 — ${{mean.toFixed(2)}} ± ${{std !== null ? std.toFixed(2) : '?'}} ${{fieldCfg.unit}}">${{displayVal}}</td>`;
      }} else {{
        cells += '<td class="no-data">–</td>';
      }}
    }}
    tbody += `<tr>${{cells}}</tr>`;
  }}

  // update filter info
  const finfo = document.getElementById('finfo-' + monthId);
  if (finfo && curFilter && filterFieldCfg) {{
    finfo.textContent = `${{matchCount}} cell${{matchCount !== 1 ? 's' : ''}} where ${{filterFieldCfg.label}} ∈ [${{(curFilter.val - curFilter.tol).toFixed(2)}} – ${{(curFilter.val + curFilter.tol).toFixed(2)}}] ${{filterFieldCfg.unit}}`;
  }} else if (finfo) {{
    finfo.textContent = '';
  }}

  const area = document.getElementById('table-area-' + monthId);
  area.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>${{thead}}</tr></thead>
        <tbody>${{tbody}}</tbody>
      </table>
    </div>
    <div class="legend">
      <span class="leg-item" style="background:rgb(30,100,200);color:white">0 ${{fieldCfg.unit}}</span>
      <span class="leg-item" style="background:rgb(130,70,115);color:white">~${{(fieldCfg.max/2).toFixed(0)}} ${{fieldCfg.unit}}</span>
      <span class="leg-item" style="background:rgb(230,40,30);color:white">${{fieldCfg.max}}+ ${{fieldCfg.unit}}</span>
      <span style="margin-left:8px;font-size:0.85em;color:#666">← ${{fieldCfg.label}} colour scale &nbsp;|&nbsp; 🟡 gold border = std &lt; ${{fieldCfg.lowStd}} ${{fieldCfg.unit}}</span>
    </div>`;

  // update heading
  const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const filterDesc = curFilter && filterFieldCfg ? ` · filter: ${{filterFieldCfg.label}} ${{curFilter.val}}±${{curFilter.tol}}` : '';
  document.getElementById('heading-' + monthId).textContent =
    `${{MONTHS[mNum-1]}} — Day ${{String(day).padStart(2,'0')}} — ${{fieldCfg.label}} mean ± std (${{fieldCfg.unit}})${{filterDesc}}`;
}}

function switchField(monthId, fieldKey) {{
  curField = fieldKey;
  document.querySelectorAll('#fieldnav-' + monthId + ' .field-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + monthId + '-f' + fieldKey).classList.add('active');
  if (curDay !== null) renderTable(monthId, curDay, fieldKey);
}}

function switchDay(monthId, day) {{
  curDay = day;
  document.querySelectorAll('#daynav-' + monthId + ' .day-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + monthId + '-d' + String(day).padStart(2,'0')).classList.add('active');
  renderTable(monthId, day, curField);
}}

function switchTab(id) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(id).style.display = 'block';
  document.getElementById('btn-' + id).classList.add('active');
  curMonth = id;
  curDay = null;
  // reset field to first active
  curField = FIELDS[0].key;
  document.querySelectorAll('#fieldnav-' + id + ' .field-btn').forEach((b,i) => {{
    b.classList.toggle('active', i === 0);
  }});
  // sync filter inputs to current filter state
  if (curFilter) {{
    const fval = document.getElementById('fval-' + id);
    const ftol = document.getElementById('ftol-' + id);
    const ffield = document.getElementById('ffield-' + id);
    if (fval) fval.value = curFilter.val;
    if (ftol) ftol.value = curFilter.tol;
    if (ffield) ffield.value = curFilter.field;
  }}
  // click first day
  const firstDayBtn = document.querySelector('#daynav-' + id + ' .day-btn');
  if (firstDayBtn) firstDayBtn.click();
}}

// boot
var first = '{first_month_id}';
if (first) switchTab(first);
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description='Generate monthly wind turbine HTML report')
    parser.add_argument('--farm', default='kelmarsh', help='Farm name (default: kelmarsh)')
    parser.add_argument('--turbine', default='turbine_2', help='Turbine name (default: turbine_2)')
    parser.add_argument('--output', default=REPORT_PATH, help='Output HTML file path')
    args = parser.parse_args()

    print(f'Loading summary files for {args.farm}/{args.turbine} ...')
    data = load_summaries(args.farm, args.turbine)
    total = sum(len(hs) for m in data.values() for d in m.values() for hs in d.values())
    print(f'  Loaded {total} hour records | {len(set(y for m in data.values() for d in m.values() for y in d))} years | {sum(len(d) for m in data.values() for d in m.values())} day-years')

    if not data:
        print('No data found. Check farm/turbine names and output directory.')
        return

    html = render_html(args.farm, args.turbine, data)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Report saved to: {args.output}')


if __name__ == '__main__':
    main()

