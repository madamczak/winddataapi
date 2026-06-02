"""Rebuild apicrawler_machines.json from scratch (clean, original 6-panel version)."""
import json
import os

DS = "${DS_LOKI}"

def stat_panel(pid, title, desc, grid, expr, display_name, calcs, color_mode, mappings=None, thresholds=None, fixed_color=None):
    fc_defaults = {
        "unit": "short",
        "noValue": "0",
        "displayName": display_name,
    }
    if mappings:
        fc_defaults["mappings"] = mappings
        fc_defaults["color"] = {"mode": "thresholds"}
        fc_defaults["thresholds"] = thresholds
    elif fixed_color:
        fc_defaults["color"] = {"mode": "fixed", "fixedColor": fixed_color}
    else:
        fc_defaults["color"] = {"mode": "thresholds"}
        fc_defaults["thresholds"] = thresholds

    return {
        "id": pid,
        "title": title,
        "description": desc,
        "type": "stat",
        "gridPos": grid,
        "datasource": {"type": "loki", "uid": DS},
        "options": {
            "reduceOptions": {"calcs": calcs, "fields": "", "values": False},
            "colorMode": color_mode,
            "graphMode": "none",
            "justifyMode": "center",
            "textMode": "auto",
            "orientation": "auto",
        },
        "fieldConfig": {"defaults": fc_defaults, "overrides": []},
        "targets": [
            {
                "datasource": {"type": "loki", "uid": DS},
                "editorMode": "code",
                "expr": expr,
                "legendFormat": display_name,
                "queryType": "instant",
                "refId": "A",
            }
        ],
    }

active_inactive_mappings = [
    {"type": "value",  "options": {"0": {"text": "IDLE",   "color": "#404040", "index": 0}}},
    {"type": "range",  "options": {"from": 1, "to": 9999, "result": {"text": "ACTIVE", "color": "green", "index": 1}}},
]
active_thresholds = {
    "mode": "absolute",
    "steps": [{"color": "#404040", "value": None}, {"color": "green", "value": 1}],
}

dashboard = {
    "__inputs": [
        {
            "name": "DS_LOKI",
            "label": "Loki",
            "description": "Loki data source (app=apicrawler)",
            "type": "datasource",
            "pluginId": "loki",
            "pluginName": "Loki",
        }
    ],
    "__requires": [
        {"type": "grafana",    "id": "grafana",    "name": "Grafana",   "version": "10.0.0"},
        {"type": "datasource", "id": "loki",       "name": "Loki",      "version": "1.0.0"},
        {"type": "panel",      "id": "stat",       "name": "Stat",      "version": ""},
        {"type": "panel",      "id": "logs",       "name": "Logs",      "version": ""},
    ],
    "title": "API Crawler \u2014 Machine Status",
    "uid": "apicrawler-machines-v1",
    "description": "Which Pi is currently running. Loki labels: app=apicrawler, pi=pi1|pi2|pi3, level.",
    "tags": ["apicrawler"],
    "schemaVersion": 38,
    "version": 1,
    "refresh": "30s",
    "time": {"from": "now-3h", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "editable": True,
    "graphTooltip": 0,
    "id": None,
    "links": [],
    "templating": {
        "list": [
            {
                "current": {
                    "selected": True,
                    "text": "grafanacloud-adamczakmateusz-logs",
                    "value": "grafanacloud-logs",
                },
                "hide": 0,
                "label": "Logs source",
                "name": "DS_LOKI",
                "options": [],
                "pluginId": "loki",
                "refresh": 1,
                "type": "datasource",
            }
        ]
    },
    "annotations": {"list": []},
    "panels": [
        {
            "type": "row",
            "id": 10,
            "title": "Machine status  (active = log line seen in last 20 min)",
            "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
        },
        stat_panel(
            1, "Pi 1",
            "Green = sent a log line in the last 20 minutes. Grey = idle.",
            {"h": 5, "w": 8, "x": 0, "y": 1},
            'count_over_time({app="apicrawler", pi="pi1", level="info"}[20m])',
            "pi1", ["lastNotNull"], "background",
            mappings=active_inactive_mappings, thresholds=active_thresholds,
        ),
        stat_panel(
            2, "Pi 2",
            "Green = sent a log line in the last 20 minutes. Grey = idle.",
            {"h": 5, "w": 8, "x": 8, "y": 1},
            'count_over_time({app="apicrawler", pi="pi2", level="info"}[20m])',
            "pi2", ["lastNotNull"], "background",
            mappings=active_inactive_mappings, thresholds=active_thresholds,
        ),
        stat_panel(
            3, "Pi 3",
            "Green = sent a log line in the last 20 minutes. Grey = idle.",
            {"h": 5, "w": 8, "x": 16, "y": 1},
            'count_over_time({app="apicrawler", pi="pi3", level="info"}[20m])',
            "pi3", ["lastNotNull"], "background",
            mappings=active_inactive_mappings, thresholds=active_thresholds,
        ),
        stat_panel(
            4, "Matches found (last 24 h)",
            "Log lines containing 'MATCH #' across all pis.",
            {"h": 4, "w": 6, "x": 0, "y": 6},
            'count_over_time({app="apicrawler"} |= "MATCH #" [24h])',
            "Matches", ["sum"], "value",
            fixed_color="blue",
        ),
        stat_panel(
            5, "Warnings (last 24 h)",
            "API request failures / retries across all pis.",
            {"h": 4, "w": 6, "x": 6, "y": 6},
            'count_over_time({app="apicrawler", level="warning"} [24h])',
            "Warnings", ["sum"], "background",
            thresholds={
                "mode": "absolute",
                "steps": [
                    {"color": "green",  "value": None},
                    {"color": "orange", "value": 1},
                    {"color": "red",    "value": 20},
                ],
            },
        ),
        # ── Farm queried per Pi row ──────────────────────────────────────────
        {
            "type": "row",
            "id": 20,
            "title": "Farm queried per Pi",
            "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 10},
        },
        # One stat panel per Pi showing kelmarsh / penmanshiel counts side-by-side
        {
            "id": 21,
            "title": "Pi 1 — farm activity",
            "description": "How many log lines pi1 sent per farm in the selected window.",
            "type": "stat",
            "gridPos": {"h": 4, "w": 8, "x": 0, "y": 11},
            "datasource": {"type": "loki", "uid": DS},
            "options": {
                "reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
                "colorMode": "background",
                "graphMode": "none",
                "justifyMode": "auto",
                "textMode": "auto",
                "orientation": "horizontal",
            },
            "fieldConfig": {
                "defaults": {"unit": "short", "noValue": "0", "color": {"mode": "palette-classic"}},
                "overrides": [
                    {"matcher": {"id": "byFrameRefID", "options": "K"}, "properties": [{"id": "displayName", "value": "kelmarsh"}]},
                    {"matcher": {"id": "byFrameRefID", "options": "P"}, "properties": [{"id": "displayName", "value": "penmanshiel"}]},
                ],
            },
            "targets": [
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi1", farm="kelmarsh"} [$__range]))', "legendFormat": "kelmarsh", "queryType": "instant", "refId": "K"},
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi1", farm="penmanshiel"} [$__range]))', "legendFormat": "penmanshiel", "queryType": "instant", "refId": "P"},
            ],
        },
        {
            "id": 22,
            "title": "Pi 2 — farm activity",
            "description": "How many log lines pi2 sent per farm in the selected window.",
            "type": "stat",
            "gridPos": {"h": 4, "w": 8, "x": 8, "y": 11},
            "datasource": {"type": "loki", "uid": DS},
            "options": {
                "reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
                "colorMode": "background",
                "graphMode": "none",
                "justifyMode": "auto",
                "textMode": "auto",
                "orientation": "horizontal",
            },
            "fieldConfig": {
                "defaults": {"unit": "short", "noValue": "0", "color": {"mode": "palette-classic"}},
                "overrides": [
                    {"matcher": {"id": "byFrameRefID", "options": "K"}, "properties": [{"id": "displayName", "value": "kelmarsh"}]},
                    {"matcher": {"id": "byFrameRefID", "options": "P"}, "properties": [{"id": "displayName", "value": "penmanshiel"}]},
                ],
            },
            "targets": [
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi2", farm="kelmarsh"} [$__range]))', "legendFormat": "kelmarsh", "queryType": "instant", "refId": "K"},
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi2", farm="penmanshiel"} [$__range]))', "legendFormat": "penmanshiel", "queryType": "instant", "refId": "P"},
            ],
        },
        {
            "id": 23,
            "title": "Pi 3 — farm activity",
            "description": "How many log lines pi3 sent per farm in the selected window.",
            "type": "stat",
            "gridPos": {"h": 4, "w": 8, "x": 16, "y": 11},
            "datasource": {"type": "loki", "uid": DS},
            "options": {
                "reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
                "colorMode": "background",
                "graphMode": "none",
                "justifyMode": "auto",
                "textMode": "auto",
                "orientation": "horizontal",
            },
            "fieldConfig": {
                "defaults": {"unit": "short", "noValue": "0", "color": {"mode": "palette-classic"}},
                "overrides": [
                    {"matcher": {"id": "byFrameRefID", "options": "K"}, "properties": [{"id": "displayName", "value": "kelmarsh"}]},
                    {"matcher": {"id": "byFrameRefID", "options": "P"}, "properties": [{"id": "displayName", "value": "penmanshiel"}]},
                ],
            },
            "targets": [
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi3", farm="kelmarsh"} [$__range]))', "legendFormat": "kelmarsh", "queryType": "instant", "refId": "K"},
                {"datasource": {"type": "loki", "uid": DS}, "editorMode": "code", "expr": 'sum(count_over_time({app="apicrawler", pi="pi3", farm="penmanshiel"} [$__range]))', "legendFormat": "penmanshiel", "queryType": "instant", "refId": "P"},
            ],
        },

        # ── Logs row ─────────────────────────────────────────────────────────
        {
            "type": "row",
            "id": 30,
            "title": "Logs",
            "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": 15},
        },
        {
            "id": 6,
            "title": "Live logs \u2014 INFO only",
            "description": "Latest INFO log lines from all pis. Expand a line to see farm, pattern, pi labels.",
            "type": "logs",
            "gridPos": {"h": 12, "w": 24, "x": 0, "y": 16},
            "datasource": {"type": "loki", "uid": DS},
            "options": {
                "dedupStrategy": "none",
                "enableLogDetails": True,
                "prettifyLogMessage": False,
                "showLabels": True,
                "showTime": True,
                "sortOrder": "Descending",
                "wrapLogMessage": False,
            },
            "targets": [
                {
                    "datasource": {"type": "loki", "uid": DS},
                    "editorMode": "code",
                    "expr": '{app="apicrawler", level="info"}',
                    "legendFormat": "",
                    "queryType": "range",
                    "refId": "A",
                }
            ],
        },
    ],
}

out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "apicrawler_machines.json")
out_path = os.path.normpath(out_path)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2, ensure_ascii=False)

size = os.path.getsize(out_path)
print(f"Written {out_path}  ({size:,} bytes)")

