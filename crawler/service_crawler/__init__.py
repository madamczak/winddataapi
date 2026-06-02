"""
service_crawler — Pre/Post Scheduled Maintenance Analysis.

For each scheduled maintenance event on a turbine, this crawler:

  Phase A — Fetch Events
      Query the API for all "Scheduled Maintenance" events in the farm's
      data range and persist them to service_crawler.db.

  Phase B — Collect Window Data
      For each event, crawl 7 days immediately BEFORE the service start
      and 7 days immediately AFTER the service end.  Data is stored as
      hourly operating-condition-binned temperature observations.

  Phase C — Delta Analysis
      For each (event, bin, col) that has sufficient pre AND post data,
      compute:
          delta = mean_post − mean_pre
      A negative delta means the component ran cooler after the service —
      the expected outcome (fresh oil, replaced bearings, cleaned contacts).
      A positive delta means the component is hotter after the service,
      which warrants investigation.

  Phase D — Report
      Print a severity-sorted summary table to stdout and persist all
      service_delta rows to service_crawler.db.

Severity scale (based on delta °C):
    IMPROVED          delta ≤ −3.0 °C   (clear thermal improvement)
    SLIGHT_IMPROVEMENT −3.0 < delta ≤ −1.0
    NEUTRAL            −1.0 < delta < +1.0
    SLIGHT_DECLINE     +1.0 ≤ delta < +3.0
    WORSENED           delta ≥ +3.0 °C  (hotter after service — investigate)

Entry point: run.py
    python -m service_crawler --farm kelmarsh
    python -m service_crawler --farm kelmarsh --turbines turbine_1,turbine_3
    python -m service_crawler --farm penmanshiel --window-days 14
"""

