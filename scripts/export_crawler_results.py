"""
export_crawler_results.py
Consolidates all *.jsonl files from crawler/apicrawler/results (and its Pi
subdirectories 1, 2, 3) into a single frontend/public/crawler_results.json.

Usage:
    python scripts/export_crawler_results.py
"""
import json
import pathlib
import datetime
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS_ROOT = ROOT / "crawler" / "apicrawler" / "results"
OUT_FILE     = ROOT / "frontend" / "public" / "crawler_results.json"

PATTERN_META = {
    "high_wind_full_spin": {
        "label":       "High Wind – Full Spin",
        "description": "All 6 turbines producing near-rated power (~2 MW) simultaneously. "
                       "Wind speed 11–15 m/s, low std dev — stable high-output hours.",
        "icon":        "💨",
        "color":       "blue",
    },
    "blade_rpm_15": {
        "label":       "Rotor at 15 RPM",
        "description": "Turbines locked at ~15.16 RPM with very tight standard deviation (<0.1). "
                       "Represents rated rotor speed under moderate-to-high winds.",
        "icon":        "🔄",
        "color":       "indigo",
    },
    "farm_stopped": {
        "label":       "Entire Farm Stopped",
        "description": "All turbines at 0 kW output for the full hour. "
                       "Likely a coordinated shutdown, grid request, or calm period.",
        "icon":        "🛑",
        "color":       "red",
    },
    "low_wind_cutin": {
        "label":       "Low Wind – Cut-in Region",
        "description": "Wind speed 3–6 m/s, all turbines just above cut-in threshold, "
                       "generating 150–300 kW each. Power curve cut-in region.",
        "icon":        "🌬️",
        "color":       "green",
    },
    "partial_performance": {
        "label":       "Partial Performance",
        "description": "Farm generating power but well below rated capacity. "
                       "Wide spread between turbines indicates curtailment or individual faults.",
        "icon":        "⚡",
        "color":       "orange",
    },
}


def load_jsonl(path: pathlib.Path) -> list[dict]:
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except json.JSONDecodeError:
                pass  # skip truncated/corrupt lines
    except FileNotFoundError:
        pass
    return records


def main():
    # Collect from root dir + subdirs 1, 2, 3
    subdirs = [RESULTS_ROOT] + [RESULTS_ROOT / d for d in ("1", "2", "3")]

    # pattern_name → { "date_hour_key" → record }  (deduplicate by farm+date+hour)
    by_pattern: dict[str, dict[str, dict]] = defaultdict(dict)

    for subdir in subdirs:
        if not subdir.exists():
            continue
        for jsonl_file in sorted(subdir.glob("*.jsonl")):
            # Filename format: {farm}_{pattern}.jsonl
            stem = jsonl_file.stem  # e.g. kelmarsh_high_wind_full_spin
            # strip farm prefix (first segment before _)
            parts = stem.split("_", 1)
            if len(parts) != 2:
                continue
            pattern_name = parts[1]  # e.g. high_wind_full_spin

            for rec in load_jsonl(jsonl_file):
                farm  = rec.get("farm", "")
                date  = rec.get("date", "")
                hour  = rec.get("hour", "")
                key   = f"{farm}_{date}_{hour}"
                if key not in by_pattern[pattern_name]:
                    by_pattern[pattern_name][key] = rec

    # Build output structure
    patterns_out = {}
    for pattern_name, slots_dict in sorted(by_pattern.items()):
        meta = PATTERN_META.get(pattern_name, {
            "label": pattern_name.replace("_", " ").title(),
            "description": "",
            "icon": "📊",
            "color": "gray",
        })
        # Sort slots chronologically
        slots = sorted(slots_dict.values(), key=lambda r: (r.get("date",""), r.get("hour",0)))
        patterns_out[pattern_name] = {
            **meta,
            "count": len(slots),
            "slots": slots,
        }

    output = {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_slots":  sum(p["count"] for p in patterns_out.values()),
        "patterns":     patterns_out,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"✓ Written {output['total_slots']} unique slots across {len(patterns_out)} patterns → {OUT_FILE}")


if __name__ == "__main__":
    main()

