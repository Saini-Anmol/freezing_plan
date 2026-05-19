---
name: Root Cause Mappings
description: Standard KPI symptom to module/function mappings discovered across study runs
type: project
---

## Standard mappings (from CLAUDE.md system prompt)

| Symptom | Suspected module/function |
|---|---|
| Low utilization | `moulds_manager.roll` auto-rotate fallback; check df_allow + open_demand search |
| Low fulfillment | Continuity locking in LP, or `actuals_simulator` factor band, or revision merge logic |
| High schedule nervousness | LP penalty weight or revision shocks |
| Excessive forced rotations | `moulds_manager` finishing too many SKUs early (priority/quantity mismatch) |

## Discovered mappings (from Apr 2026 CTP run)

### Machine type mismatch → false low utilization
- **Symptom:** Avg Util% reported ~25 pts below Ideal; Machine Utilization sheet has more rows than physical machines
- **Cause:** LP's `_build_continuity()` (jk_curing_lp_PCR.py line 1180) converts Machine to `str`; LP Scheduled rows stay `int`. Mixed types in `today_actuals` DF. `groupby("Machine")` in `kpi_calculator.build_simulated_machine_utilization()` creates duplicate rows.
- **Fix location:** `V1/routes/daily_route.py:_extract_today_production()` — normalize Machine column to consistent type (e.g. `int`) after filtering today's rows.
- **Detection:** Machine Utilization row count > unique physical machine count. Check for both str and int Machine entries for the same machine number.
- **NOT a real idle-machine problem.** Fulfillment is healthy, today_actuals.csv shows correct production. The 93%+ true utilization means machines are actually well-utilized.

### End-of-study rotation spike (Day 26-29)
- **Symptom:** 14/27/29 rotations on late days; daily scheduled units drop from ~14,000 to ~7,000-10,000
- **Cause:** Multiple SKUs (esp. 1325221417096HURL0 and 1325214812074TUHL0) finish simultaneously at horizon end, triggering batch auto-rotations. Expected behavior, not a bug.
- **Note:** The To_SKU on Day 29 is concentrated on 1325221318095HURL0 and 1D25114012008QXPC0 — both high-priority unmet SKUs. auto-rotate is working correctly.
