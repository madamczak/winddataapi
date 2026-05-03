"""
Generate rotor speed and power charts from rated_rotor_hours.txt using matplotlib,
then embed them as base64 PNGs into the Charts tab of similar_days_report.html.
"""
import base64
import io
import os
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), '..')
TXT_FILE = os.path.join(ROOT, 'rated_rotor_hours.txt')
HTML_FILE = os.path.join(ROOT, 'similar_days_report.html')

YEAR_COLORS = {
    2017: '#e67e22', 2018: '#f1c40f', 2019: '#2ecc71',
    2020: '#1abc9c', 2021: '#3498db', 2022: '#9b59b6', 2023: '#e91e63',
}

MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun',
                'Jul','Aug','Sep','Oct','Nov','Dec']


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
        dt = datetime.strptime(hour_start, '%Y-%m-%d %H:%M:%S')
        rows.append({'dt': dt, 'year': year,
                     'wind': wind_mean, 'power': power_mean, 'rotor': rotor_mean})
    return rows


def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def make_chart(rows, field, ylabel, title, color_map):
    """Scatter plot: x=sequential row index (chronological), colored by year.
    Black horizontal average line per year with value label."""
    fig, ax = plt.subplots(figsize=(14, 5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#f8f9fa')
    ax.grid(True, linestyle='--', alpha=0.5, color='#ccc')

    xs = list(range(len(rows)))
    ys = [r[field] for r in rows]
    colors = [color_map.get(r['year'], '#999') for r in rows]

    ax.scatter(xs, ys, s=10, c=colors, alpha=0.75, zorder=3)

    # Per-year average lines (black) spanning the full year range, with label
    by_year_last = {}
    by_year_idx_tmp = {}
    for i, r in enumerate(rows):
        by_year_idx_tmp.setdefault(r['year'], []).append(i)

    for year in sorted(by_year_idx_tmp):
        idxs = by_year_idx_tmp[year]
        yr_avg = sum(ys[i] for i in idxs) / len(idxs)
        ax.hlines(yr_avg, idxs[0], idxs[-1],
                  color='black', linewidth=2, linestyle='-', alpha=0.9, zorder=5)
        by_year_last[year] = (idxs[-1], yr_avg)

    # Label each year at end of its line
    for year, (x_end, avg_val) in sorted(by_year_last.items()):
        ax.text(x_end + len(rows) * 0.005, avg_val,
                f'{year}: {avg_val:.2f}',
                color='black', fontsize=7.5, va='center', fontweight='bold')

    # Legend entries per year
    for year in sorted(set(r['year'] for r in rows)):
        ax.scatter([], [], s=30, color=color_map.get(year, '#999'), label=str(year))

    ax.set_title(title, fontsize=13, fontweight='bold', color='#1a2540', pad=10)
    ax.set_ylabel(ylabel, fontsize=10, color='#333')
    ax.set_xlabel('Sample index (chronological order)', fontsize=10, color='#333')
    ax.tick_params(colors='#555')
    for spine in ax.spines.values():
        spine.set_edgecolor('#ccc')

    ax.legend(title='Year', title_fontsize=9, fontsize=8,
              loc='upper right', framealpha=0.9,
              ncol=2 if len(by_year_last) > 5 else 1)

    # Trend annotation for power chart
    if field == 'power':
        year_means = {y: sum(ys[i] for i in idxs) / len(idxs)
                      for y, idxs in by_year_idx_tmp.items()}
        years_sorted = sorted(year_means)
        if len(years_sorted) >= 2:
            first_y, last_y = years_sorted[0], years_sorted[-1]
            slope = (year_means[last_y] - year_means[first_y]) / (last_y - first_y)
            direction = '↑' if slope > 5 else ('↓' if slope < -5 else '→')
            ax.annotate(
                f'Avg trend: {slope:+.1f} kW/yr  {direction}',
                xy=(0.02, 0.95), xycoords='axes fraction',
                fontsize=9, color='#1a2540',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffcc', alpha=0.8)
            )

    fig.tight_layout()
    return fig


def main():
    print('Parsing rated_rotor_hours.txt ...')
    rows = parse_txt(TXT_FILE)
    print(f'  {len(rows)} data points loaded')

    print('Generating rotor speed chart ...')
    fig_rotor = make_chart(
        rows, 'rotor', 'Rotor Speed (RPM)',
        'Rotor Speed at Rated Conditions (mean 14.8–15.2 RPM, std < 0.05)',
        YEAR_COLORS
    )
    rotor_b64 = fig_to_b64(fig_rotor)
    plt.close(fig_rotor)

    print('Generating power chart ...')
    fig_power = make_chart(
        rows, 'power', 'Power (kW)',
        'Power Output at Rated Rotor Speed (same filtered hours)',
        YEAR_COLORS
    )
    power_b64 = fig_to_b64(fig_power)
    plt.close(fig_power)

    charts_html = f"""
<!-- ===== CHARTS TAB ===== -->
<div class="tab-panel" id="tab-charts" style="display:none">
  <div class="chart-wrap">
    <img src="data:image/png;base64,{rotor_b64}" style="width:100%;border-radius:4px" alt="Rotor Speed Chart">
  </div>
  <div class="chart-wrap">
    <img src="data:image/png;base64,{power_b64}" style="width:100%;border-radius:4px" alt="Power Chart">
  </div>
</div>"""

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    if 'tab-charts' in html:
        html = re.sub(
            r'<!-- ===== CHARTS TAB ===== -->.*?</div>\s*</div>',
            charts_html.strip(),
            html, flags=re.DOTALL
        )
    else:
        last_div = html.rfind('</div>')
        html = html[:last_div] + charts_html + '\n</div>' + html[last_div + len('</div>'):]

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Charts embedded in: {HTML_FILE}')


if __name__ == '__main__':
    main()

