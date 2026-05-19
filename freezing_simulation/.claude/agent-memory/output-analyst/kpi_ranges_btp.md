---
name: BTP KPI Ranges and Patterns
description: Healthy and observed KPI ranges for BTP 30-day study; includes the critical str/int machine ID duplicate bug
type: project
---

BTP 30-day study (May 2026) observed KPI ranges and known issues.

**Why:** Baseline for future run comparisons and bug triage.

**How to apply:** When analyzing a new BTP run, compare against these ranges to spot regressions or improvements.

## Observed KPIs (May 2026 run, regenerated with 2nd iterative demand)

| KPI | Reported | True (corrected) | Target |
|---|---|---|---|
| Demand (Latest Revised) | 727,835 | same | — |
| Demand (Day-1 Original) | 685,215 | same | — |
| Actual Produced | 663,403 | same | — |
| Fulfillment vs Latest | 91.1% | same | >75% |
| Fulfillment vs Day-1 | 92.7% | same | >75% |
| Avg Press Utilization | 63.6% | ~89% (after dedup) | >85% |
| Total Changeovers | 481 | same | minimize |
| LP-Scheduled COs | 102 | same | — |
| Wrapper-Forced COs | 379 | same | — |
| Mould Cleans | 56 | same | — |
| SKUs FULLY MET | 65/99 | same | — |
| SKUs PARTIAL | 31/99 | same | — |
| SKUs UNMET | 3/99 | same | — |

## Critical Bug: Machine Utilization str/int Duplicate Machine IDs

The `Machine Utilization` sheet in both BTP and CTP reports contains duplicate rows for the same physical machine:
- **68 duplicate pairs in BTP** (238 rows, 170 unique machines)
- **32 duplicate pairs in CTP** (122 rows, 90 unique machines)

Root cause: `kpi_calculator.build_simulated_machine_utilization()` calls `df.groupby("Machine")` on a DataFrame where the `Machine` column contains a mix of `str` and `int` types. Pandas creates separate groups for `int 14801` vs `str '14801'`. The LP output rows have string machine IDs; the Day-1 initial mould-state rows have integer machine IDs.

Fix location: `V1/reports/kpi_calculator.py` line ~162 in `build_simulated_machine_utilization`. Add `df['Machine'] = df['Machine'].astype(str)` before the groupby. Same fix needed in `build_simulated_machine_schedule` (line ~141).

**True utilization after dedup:**
- BTP: 89.0% avg (170 machines) — ABOVE 85% target
- CTP: 93.1% avg (90 machines) — ABOVE 85% target

Both plants pass the utilization target once the bug is fixed.

## Changeover Pattern

Phase 1 (Days 1-10): 24 LP + 10 forced = 34 total
Phase 2 (Days 11-20): 49 LP + 50 forced = 99 total (post-Day-11 revision)  
Phase 3 (Days 21-30): 29 LP + 319 forced = 348 total (SKU-completion cascade)

The forced rotation surge in Phase 3 is the natural behavior of a 30-day simulation: as SKUs complete, moulds_manager.roll() picks up idle presses. The top target SKUs (VURL0, HURL1, PSKP0) end up FULLY MET because of these rotations. TURL0 and SRBT0 remain PARTIAL despite receiving rotations — their demand is large relative to eligible machine capacity.

## Throughput Pattern

- Days 1-16: avg 24,932 units/day (high, many machines active)
- Days 17-30: avg 19,624 units/day (21% lower — SKU completions cause multi-SKU churn)
- Late-month (Day 30): only 9,918 scheduled — the LP sees small remaining open demand
  and spreads it thinly; most machines have no compatible remaining demand

## Partial SKU Root Causes

1. `1325214812074TUHL0`: 51.5% fulfilled — largest gap (11,953). Large demand (24,647) with 43 eligible machines. LP did not allocate enough machine-time. Related to continuity locking.
2. `1D25215013008SXC11`: 26.4% fulfilled — 0 eligible machines in LP data (CycleTime=0). This is an unschedulable SKU showing as PARTIAL (produced via forced rotations to compatible machines, but LP cannot plan it). Likely a master data gap.
3. `1325217613082TUNE0`: 20.5% fulfilled — also 0 eligible machines. Same issue as above.
