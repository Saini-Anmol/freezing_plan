---
name: Reference per-day run artifacts
description: Where to find sample LP outputs and per-day artifacts for cross-checking diagnoses.
type: reference
---

Per-day audit dumps live under `freezing_simulation/runs/<plant>/YYYY-MM-DD/`:
- `lp_shift_schedule_30day.csv` — full 30-day LP shift schedule (raw `lp_results["shift_schedule"]`). Useful for verifying continuity-vs-LP row split (filter on `Remarks` containing "Continuity" or "LP Scheduled").
- `today_actuals.csv` — post-factor production for today, derived from `today_prod`. After type fixes, this is the place to verify Machine normalization.
- `lp_demand_fulfillment.csv`, `lp_machine_utilization.csv` — LP's per-day output sheets.
- `actuals_factors.json` — `{sku: factor}` map drawn for that day.
- `summary.json` — one-line day summary.

Master cache lives under `freezing_simulation/inputs/<plant>/masters/`:
- `machine_allowable.xlsx` — `Machines` column is a string-serialized list of ints (e.g., `"[3609, 3610, ...]"`), parsed via `ast.literal_eval` in `master_data.load`.

Quick repro for the Machine type bug:
```python
df = pd.read_csv("freezing_simulation/runs/ctp/2026-04-19/lp_shift_schedule_30day.csv")
# CSV roundtrip auto-infers int64; the in-memory bug only manifests pre-CSV.
# To reproduce in-memory, instantiate two DataFrames with str + int Machine, concat, groupby.
```
