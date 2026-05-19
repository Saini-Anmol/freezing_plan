---
name: CTP Machine Util Bug - String vs Int Machine ID
description: Root cause of the 68.68% avg utilization artifact in Apr 2026 CTP 30-day study — LP returns mixed str/int Machine types causing groupby to split each Continuity machine into two rows
type: project
---

The LP's `_build_continuity()` function (jk_curing_lp_PCR.py line 1180) explicitly converts Machine to string:
`mach = str(row["Machine"])`. LP Scheduled rows use integer Machine from the allocation engine.

This causes the `lp_shift_schedule` DataFrame to have MIXED Machine types: strings for Continuity rows and integers for LP Scheduled rows.

`daily_route._extract_today_production()` passes this mixed-type DataFrame through without normalizing the Machine column. The `today_actuals` in-memory DataFrame therefore contains mixed types.

`kpi_calculator.build_simulated_machine_utilization()` calls `groupby("Machine")` which treats `'3609'` (str) and `3609` (int) as DIFFERENT groups. Result: 32 machines that have both Continuity and LP Scheduled production appear TWICE in Machine Utilization — once as string (carrying ~95–100% utilization from Continuity work), once as integer (carrying 0–5% utilization from the few LP Scheduled rows).

The reported average is computed over 122 rows instead of 90 unique machines, dragging it from the true ~93.1% down to 68.68%.

**Why:** LP source stores Machine as str internally (line 1180) — cannot modify LP.

**How to apply:** When diagnosing low utilization on future runs, first check if Machine Utilization sheet row count > unique physical machine count. If 122 rows show up for 90 machines, this bug is active. The fix belongs in `daily_route._extract_today_production()` — add `.astype(int)` or `.astype(str)` to normalize Machine column after filtering today's rows.

Also affects: Machine Schedule sheet (same groupby issue), Actual_Total_Units column.
Does NOT affect: Demand Fulfillment, Per-Day History, Forced Rotations Log (all keyed by SKU or use cumulative_actuals).

Corrected true avg util for Apr 2026 CTP run: ~93.1% (computed by merging str+int entries per machine).
