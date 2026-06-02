"""
degradation_crawler — Wind Turbine Degradation Detection Pipeline.

Architecture overview (see docs/degradation_crawler_design.html):

  Phase 1 — Baseline:    baseline.py  — crawl 6–12 healthy months, build T_baseline[bin]
  Phase 2 — Scan:        scan.py      — crawl subsequent months, compute ΔT residuals
  Phase 3 — Service Mask:service_mask.py — exclude maintenance windows
  Phase 4 — Drift Detect:drift_detect.py — rolling 30-day mean, flag when ΔT drifts
  Phase 5 — Alert:       alert.py     — write JSONL outputs, push to Loki

Entry point: run.py
"""

