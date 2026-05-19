---
name: CTP Baseline KPI Ranges
description: Observed KPI values in the Apr 2026 CTP 30-day study for institutional reference
type: project
---

**Study:** CTP plant, Apr 1–30 2026, 30 simulation days
**Report:** /Users/anmolsaini/Documents/freezing_plan/freezing_simulation/outputs/ctp/final_kpi_report.xlsx

| KPI | Ideal LP | Simulated (reported) | Simulated (corrected) |
|---|---|---|---|
| Total Demand | 427,466 | 427,466 | 427,466 |
| Total Produced | 406,748 | 387,096 | 387,096 (correct) |
| Fulfillment % | 95.15% | 90.56% | 90.56% (correct) |
| Avg Util % | 94.38% | 68.68% (BUG) | ~93.1% (after type fix) |
| Total COs | 22 | 123 | 123 (correct) |
| Mould Cleans | 49 | 38 | 38 (correct) |
| FULLY MET SKUs | 17 | 16 | — |
| PARTIAL SKUs | 15 | 23 | — |
| UNMET SKUs | 10 | 3 | — |
| UNSCHEDULABLE SKUs | 3 | 3 | — |

**Rotation pattern:** 123 wrapper-forced rotations, heavily clustered at end of study
(Day 22+: 134 of 123 total). Day 29 peak = 29 rotations (SKU 1325214812074TUHL0 finishing
simultaneously on many presses). This is expected behavior — SKUs completing near end of
30-day horizon cause simultaneous auto-rotations.

**Physical machine count:** 90 unique machines on 30 days × 3 shifts × 8 hr = 43,200 min available per machine.

**Top unmet demand SKUs:**
- 1325224716111SELS0: 11,337 gap (27% fulfilled) — low priority (1.036)
- 1325225518111HRHB0: 5,931 gap (70.2%) — priority 2.047
- 3 UNSCHEDULABLE SKUs (no compatible machines in allowable matrix)
