# Product Requirements Document — Freezing Plan Simulation

**Project:** Freezing Plan Simulation for PCR Curing Schedule
**Plants in scope:** JK Tyre & Industries Ltd. — **CTP** (active, v1 study running) and **BTP** (LP code pending; same wrapper will drive both)
**Department:** PCR Curing
**Status:** v1 — first 20-day CTP study under way; BTP onboarding pending its LP delivery
**Document type:** Business / product requirements

---

## 1. Background

JK Tyre operates two PCR plants in scope: **CTP** (currently running v1 simulation) and **BTP** (LP code being delivered). For each plant, the planning team issues a **30-day demand plan** to its Curing Department three times every month — on the **5th, 15th, and 25th**. Each new release revises the previous plan: SKU quantities typically shift by **±3%** and **new SKUs may appear**.

The Curing Department runs an **LP-based scheduler** ([`jk_curing_lp_PCR.py`](../../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py)) that produces an **optimal 30-day schedule** from a single demand snapshot. The output is "ideal" — it assumes nothing changes, all moulds behave perfectly, and the schedule will execute exactly as planned.

In reality the plant operates differently:

- The schedule is **re-generated every day** based on current ground state (which mould is on which press, mould wear, residual demand).
- Production **deviates from plan** by small amounts each day (machine inefficiency, minor stoppages, etc.).
- Every 10 days a **revised demand** arrives that must be merged into the open balance.

There is no current way to evaluate **how the daily-rerun process actually performs** vs. the LP's idealised single-shot plan. A planner needs visibility into:
- Cumulative fulfillment across the rolling horizon
- Press utilisation under daily replanning
- How many changeovers actually occur
- How the schedule "drifts" day-to-day (stability)
- The impact of revisions when they land

This project builds a **simulation wrapper** around the existing LP that mimics the daily-rerun process, ingests revisions, simulates production with realistic variance, and reports KPIs for stakeholders.

## 2. Stakeholders

| Stakeholder | Interest |
|---|---|
| **Curing Department Planner** (primary user) | Daily executable schedule + end-of-cycle KPI report |
| **Plant Manager / Department Head** | KPI report comparing simulated execution vs. ideal LP plan; basis for performance reviews |
| **CTP Team** | Awareness that their revisions are integrated faithfully and downstream impact is measured |
| **LP scheduler maintainer** (Algo8 AI / Paranjay Dodiya) | Wrapper must NOT modify the LP source — black-box dependency only |

## 3. Objectives (in priority order)

1. **Maximum demand fulfillment** — produce as much of the committed CTP demand as possible across the simulated horizon.
2. **Maximum average press utilization** — never let a press sit idle while there is unmet demand it can produce. If a SKU finishes on a press, mount the next compatible unmet SKU on that press.
3. **Minimum changeovers** — each mould swap costs 360 min (6 hours) of downtime + crew effort; minimise where it doesn't conflict with #1 and #2.

## 4. Success metrics

The simulation is considered successful if it produces, at the end of every 20–30-day study, a single Excel report (`final_kpi_report.xlsx`) containing:

| Metric | Target / interpretation |
|---|---|
| **Demand Fulfillment %** | % of original 30-day commitment produced. Comparable directly with the ideal LP's fulfillment %. |
| **Avg Press Utilization %** | % of available shift-minutes spent in production. Should be high (88%+) under the auto-rotate policy. |
| **Total Changeovers** | LP-scheduled CO + wrapper-forced CO (idle-press pickups). Should be modest, not zero. |
| **Schedule Stability** | How much today's LP plan for a future date shifts vs. yesterday's plan for the same date. Low shifts = trustworthy plan. |
| **Per-SKU status** | FULLY MET / PARTIAL / UNMET / UNSCHEDULABLE breakdown vs. original demand. |

## 5. Functional requirements

| # | Requirement |
|---|---|
| FR-1 | Load a CTP demand workbook with a base sheet ("Initial demand") and one or more revision sheets ("Revised iteration N demand") |
| FR-2 | Load a Day-1 daily running moulds CSV (consumed-life format, `LH#RH` mould pair encoding) and convert to remaining-life internally |
| FR-3 | Pull LP master data (cycle times, machine allowable matrix, GT inventory, mould master) from MySQL on first run; cache locally for subsequent runs |
| FR-4 | Run the LP for a fresh 30-day horizon every simulated day, using current open demand + current mould state as inputs |
| FR-5 | Extract Day-1 production from the LP's shift schedule, group by SKU, and sum quantities |
| FR-6 | Simulate per-SKU actual production by applying a uniform random factor in [-5%, +2%] to scheduled qty |
| FR-7 | Decrement open demand by simulated actuals; track cumulative actuals per SKU |
| FR-8 | Roll mould state to next day: decrement mould life by `actual_units / 2` cycles; auto-rotate idle presses to highest-priority compatible unmet SKU; track forced rotations in a log |
| FR-9 | On revision days (configurable), apply the rule `new_open_balance = revised_qty − cumulative_actuals` per SKU and update priority from the revision sheet |
| FR-10 | Archive every day's inputs/outputs under `runs/YYYY-MM-DD/` for full auditability |
| FR-11 | At end-of-study, produce an 8-sheet KPI workbook: 5 sheets mirroring the LP's existing output (Demand Fulfillment, Machine Schedule, Shift Schedule, Machine Utilization, Mould Tracker) + Ideal-vs-Simulated, Per-Day History, Schedule Stability, Changeover Breakdown, Forced Rotations Log |
| FR-12 | Capture an "ideal baseline" by running the LP once on Day-1 inputs; persist to `outputs/ideal_baseline/` |
| FR-13 | All operations driven from a single command: `python3 main.py --plant <ctp\|btp> [--reset \| --refresh-masters \| --smoke-test]` |
| FR-14 | All study parameters (window, paths, factor band, seed) live in `configs/<plant>.yaml` — no code edits required for typical runs |
| FR-15 | Multi-plant: state, runs, outputs, and master cache are all scoped per plant under `<dir>/<plant>/`, so two plants' studies cannot collide |

## 6. Non-functional requirements

| # | Requirement |
|---|---|
| NFR-1 | **Reproducible** — fixed `random_seed` (default 42) means two runs of the same study produce identical KPIs |
| NFR-2 | **Single-machine deployment** — runs on a planner's laptop; no cluster, server, or cloud dependency |
| NFR-3 | **Runtime ≤ 10 minutes** for a 20–30 day study |
| NFR-4 | **Idempotent state writes** — atomic write-temp-then-rename for every state file; no half-written CSVs even on crash |
| NFR-5 | **Auditable** — every simulated day archives full LP inputs, outputs, and applied factors |
| NFR-6 | **No modification of the LP source** — wrapper interfaces only via `lp_adapter.run_lp()` |
| NFR-7 | **Swappable actuals source** — when a real shop-floor data feed becomes available, only the actuals simulator module needs replacing |

## 7. Constraints & assumptions

- **Plan-as-truth-with-noise** — there is no real shop-floor data feed; the actuals simulator's output is treated as ground truth.
- **Multi-plant support** — wrapper drives both CTP and BTP via `--plant` flag; each plant's data, state, and outputs live in segregated subfolders.
- **PCR tyre type only** — TBR is out of scope for v1. Multi-tyre runs deferred.
- **No holiday calendar** — April 2026 has no holidays; this is a near-term gap to be addressed when later months need it.
- **GT inventory is informational** — the LP loads it for display but does not subtract from demand; the wrapper preserves this behaviour.
- **CTP file column contract is stable** — `SKUCode, Updated_Requirement, ConsolidatedPriorityScore` will be present in every revision file.
- **30-day LP horizon is fixed** — must not be shortened to chase runtime; the LP's optimisation depends on the full horizon.

## 8. User stories

**US-1 — Run the daily simulation**
> As a planner, I want to run a single command at the start of a study and have the system simulate every day's schedule, so that I get an end-of-cycle KPI report without manual intervention each day.

**US-2 — Apply CTP revisions automatically**
> As a planner, when CTP delivers a revised plan, I want to drop the new sheet into the existing workbook, configure the revision day in `config.yaml`, and re-run — without re-coding anything.

**US-3 — Compare ideal vs simulated**
> As a manager, I want a single sheet that shows me side-by-side: what the ideal LP plan said we'd produce vs. what the simulated daily-rerun process actually achieved. So I can quantify the cost of execution variance + replanning.

**US-4 — Audit a specific day**
> As an analyst, I want to inspect the inputs, factors, and outputs for any individual simulated day. So I can investigate anomalies without re-running the simulation.

**US-5 — Sensitivity test**
> As a planner, I want to change the actuals variance band (e.g., from [-5%, +2%] to [-10%, +1%]) and re-run to see how robust the system is to higher production noise.

## 9. Out of scope (v1)

- TBR tyre type
- Holiday-aware capacity model
- Real shop-floor production data feed
- Multi-day "frozen window" enforcement (currently revisions can change SKU qty mid-window)
- Per-machine downtime / planned-maintenance scheduling
- Demand carry-over policy beyond simple roll-forward via cumulative_actuals subtraction
- A web dashboard or API — this is a CLI / Excel deliverable

## 10. Roadmap

| Item | Trigger |
|---|---|
| Add iteration-2 revision sheet & extend study to 30 days | When CTP delivers iteration 2 |
| Holiday calendar integration | When study month has holidays |
| TBR support | When user expands scope |
| Real actuals feed replacing the simulator | When shop-floor data feed exists |
| Manager-friendly second stability metric (vs Day-1 baseline) | If consecutive-day stability proves too noisy |
| Subtract 360-min forced-CO time from next-day capacity | If KPI sensitivity demands it |
| A/B sensitivity study with multiple factor bands | When manager wants stress-test results |

## 11. Acceptance criteria

The wrapper is considered acceptance-ready when:

- ✅ `python3 main.py --smoke-test` completes successfully from a clean state
- ✅ A 20-day study produces a valid 8-sheet `final_kpi_report.xlsx`
- ✅ Demand Fulfillment % > 75% (after auto-rotate and full revision cycle)
- ✅ Avg Press Utilization > 85%
- ✅ Total Changeovers count is reported and includes both LP-scheduled + wrapper-forced
- ✅ Schedule Stability sheet contains data; row math `Actual_Qty = Scheduled_Qty × (1 + Factor_Pct/100)` validates row-by-row
- ✅ Re-running with the same seed produces identical KPIs (reproducibility)
- ✅ Adding a new revision sheet + config entry works without code change

## 12. Glossary

- **CTP** — Curing Tyre Plant (the upstream team that issues demand plans)
- **PCR** — Passenger Car Radial (the tyre category)
- **LP** — Linear Programming (the optimisation method underlying `jk_curing_lp_PCR.py`)
- **Continuity** — production blocks pre-locked for currently-mounted moulds before the LP solve
- **Changeover (CO)** — a mould swap on a press; 360 min downtime + 60 min FTC check
- **Forced rotation** — a wrapper-induced changeover triggered when a SKU finishes on a press and there is still a compatible unmet SKU available
- **Mould life** — remaining cure cycles before a mould requires cleaning (max 3,000)
- **GT Inventory** — Good-in-Transit inventory (informational only in this system)
- **Actual_*** — any column post-factor-adjusted (simulated production)
- **Scheduled_*** — any column representing LP-planned qty before the random factor
