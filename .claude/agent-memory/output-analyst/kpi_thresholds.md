---
name: KPI Thresholds and Acceptance Criteria
description: Target values and acceptance thresholds for CTP/BTP 30-day study KPIs, from CLAUDE.md and project spec
type: project
---

Per CLAUDE.md and project objectives (priority order):

| KPI | Target / Threshold | Notes |
|---|---|---|
| Demand Fulfillment % | >75% (acceptable), >90% (healthy) | Denominator = original Day-1 plan, never revised |
| Avg Press Utilization % | >85% (acceptable), >93% (healthy) | After fixing Machine type mismatch bug |
| Total Changeovers | Minimize; 0 LP-scheduled is normal | Wrapper-forced COs are expected as SKUs finish |
| Schedule Stability | Lower abs_shift = better | No hard threshold defined yet |
| Ideal vs Simulated Fulfillment gap | <5 pts acceptable | Apr 2026 CTP: 4.59 pts (acceptable) |
| Ideal vs Simulated Util gap | <5 pts acceptable | Any larger gap warrants investigation |

**Hard rules (never override):**
- Do NOT lower CHANGEOVER_PENALTY_WEIGHT
- Do NOT modify the LP source (jk_curing_lp_PCR.py)

**Typical Ideal LP values (CTP, Apr 2026 30-day study):**
- Ideal Fulfillment: 95.15%
- Ideal Avg Util: 94.38%
- Ideal LP-scheduled COs: 22
- Ideal Mould Cleans: 49
