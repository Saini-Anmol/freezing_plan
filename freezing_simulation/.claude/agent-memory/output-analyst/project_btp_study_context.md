---
name: BTP Study Context and Constraints
description: Active BTP study metadata, config, and hard constraints for the output analyst
type: project
---

BTP 30-day study (May 2026) is the active study as of 2026-05-11.

**Why:** Allows future analyst sessions to pick up context without re-reading CLAUDE.md from scratch.

**How to apply:** Use as context when analyzing new BTP runs.

## Study Parameters
- start_date: 2026-05-01, simulation_days: 30, planning_days: 30
- Revisions: Day 11 (1st iterative demand), Day 21 (2nd iterative demand)
- Demand basis: LATEST revised plan (2nd iterative, 727,835 units); Original Day-1: 685,215
- 170 unique machines (Day-1: 167 + 3 LP-added during study)
- 99 SKUs (95 in original + 4 added by revisions)

## Hard Constraints (Never Recommend)
- Do NOT modify LP source (jk_curing_lp_PCR.py)
- Do NOT lower CHANGEOVER_PENALTY_WEIGHT (currently 0.01)
- Do NOT shrink planning_days below 30

## Known Issues Identified in May 2026 Run
1. **str/int Machine ID duplicate bug** in kpi_calculator.py - artificially deflates avg utilization KPI
2. **SKUs with 0 eligible machines** (1D25215013008SXC11, 1325217613082TUNE0) showing as PARTIAL - these have no LP-schedulable path; production comes only from forced rotations
3. **Late-month forced rotation cascade** (Days 25-30: 40-61/day) - natural behavior but contributes 136,440 machine-mins of CO downtime unaccounted in Used_Mins
