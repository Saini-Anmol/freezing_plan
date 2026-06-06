# JK Tyre — PCR Curing LP Scheduler (BTP)

A **Linear-Programming–based monthly curing-schedule optimizer** for JK Tyre's
**Banmore Tyre Plant (BTP)** PCR (Passenger Car Radial) curing department.

The scheduler decides **which SKU runs on which curing press, for how many
cycles, and in what order** across a full monthly horizon (28–31 days), so that
demand is met as completely as possible while respecting press allowability,
the finite mould pool, changeover cost, and mould-cleaning downtime.

The entire approach lives in a **single, self-contained Python file** —
[`jk_curing_lp_PCR.py`](jk_curing_lp_PCR.py) — that produces one formatted Excel
workbook (the **base curing schedule**) consumed by all downstream freezing /
simulation logic.

> **TL;DR**
> ```bash
> pip3 install numpy pandas openpyxl scipy sqlalchemy pymysql
> python3 jk_curing_lp_PCR.py        # reads DB, writes <PLANT>_..._PlanSchedule.xlsx
> ```

| | |
|---|---|
| **Plant** | JK Tyre & Industries Ltd. — Banmore Tyre Plant (BTP) |
| **Department** | PCR Curing |
| **Tyre type** | PCR (Passenger Car Radial) |
| **Version** | v4 — Production |
| **Solver** | HiGHS via `scipy.optimize.linprog` (continuous LP + rounding) |
| **Designed by** | Paranjay Dodiya — Algo8 AI Pvt. Ltd. |
| **Entry class** | `JK_LP_Curing_Scheduler_v2` |

---

## Table of contents

1. [Problem in one paragraph](#1-problem-in-one-paragraph)
2. [Quick start](#2-quick-start)
3. [The five-phase pipeline](#3-the-five-phase-pipeline)
4. [Data inputs](#4-data-inputs)
5. [The LP formulation](#5-the-lp-formulation)
6. [Rounding & top-up](#6-rounding--top-up)
7. [Continuity blocks](#7-continuity-blocks)
8. [Mould tracking & eligibility](#8-mould-tracking--eligibility)
9. [Output workbook](#9-output-workbook)
10. [Configuration reference](#10-configuration-reference)
11. [Code map](#11-code-map)
12. [Assumptions & limitations](#12-assumptions--limitations)
13. [Glossary](#13-glossary)

---

## 1. Problem in one paragraph

The Banmore plant has **170 curing presses** that must produce a monthly demand
across its active PCR SKU set. Each SKU has a fixed cure (cycle) time per mould,
each press has a hard list of physically allowable presses, the mould pool is
finite, and **every SKU switch on a press costs a changeover** (300 min at BTP)
plus a **mould cleaning** every fixed number of units. The scheduler must choose
the SKU→press→cycle assignment and run order that **minimises unmet demand**
(primary) and **changeover count** (secondary tiebreaker), then lay that
allocation out shift-by-shift across the month.

The strategy is a classic **solve-then-round** decomposition:

> Solve a *continuous* LP for globally optimal press-minute allocation →
> round the fractional minutes to *integer* cure cycles → greedily top up
> any rounding shortfall → render a row-level, shift-wise schedule.

---

## 2. Quick start

### Requirements

- Python **3.9+**
- `numpy`, `pandas`, `openpyxl`, `scipy`
- `sqlalchemy` + `pymysql` *(only for the database entry point)*

```bash
pip3 install numpy pandas openpyxl scipy sqlalchemy pymysql
```

### Run from the database (default `__main__`)

The bottom of the file calls `run_from_database(...)`. It connects to the MySQL
planning database (see [Config](#10-configuration-reference)), runs all five
phases, and writes the Excel workbook named by `Config.OUTPUT_FILE`.

```bash
python3 jk_curing_lp_PCR.py
```

### Run from Excel files (no DB)

Use `run_from_excel(...)` when you have the six input datasets exported as
spreadsheets — handy for offline runs, testing, or sharing reproducible cases:

```python
from jk_curing_lp_PCR import run_from_excel
from datetime import datetime

run_from_excel(
    demand_path  = "Demand_for_Curing_Schedule3_pcr.xlsx",
    cycles_path  = "Master_Curing_Design_CycleTime_pcr.xlsx",
    allow_path   = "curing_pcr_machine_allowable.xlsx",
    gt_path      = "GT_Inventory_pcr.xlsx",
    mould_path   = "Master_Mapping_Mould_SKU.xlsx",
    running_path = "load_running_moulds.xlsx",   # optional; enables continuity
    plan_start   = datetime(2026, 5, 1, 7, 0, 0),
    output_path  = "BTP_PCR_Curing_LP_v4_Schedule.xlsx",
)
```

Both entry points return a `dict` of result DataFrames
(`machine_schedule`, `shift_schedule`, `demand_fulfillment`,
`machine_utilization`, `mould_tracker`) **and** write the Excel workbook.

---

## 3. The five-phase pipeline

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Phase 1  │ → │ Phase 2  │ → │ Phase 3  │ → │ Phase 4  │ → │ Phase 5  │
│   ETL    │   │ LP Solve │   │ Rounding │   │ Schedule │   │  Export  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
 load & clean   continuous     integer        shift-wise     formatted
 all inputs     press-minute   cure cycles     row-level      Excel
                allocation     + top-up        layout         workbook
```

| Phase | Class / method | Responsibility |
|---|---|---|
| 0 | `run_from_excel` / `run_from_database` | Load the six datasets (Excel or SQL) |
| 1 | `JK_LP_Curing_Scheduler_v2._prepare_skus` | Build the SKU table, mark schedulability |
| 2 | `JK_LP_Curing_Scheduler_v2._build_continuity` | Lock presses already running an in-demand SKU |
| 3 | `LP_Solver.solve` | Continuous press-minute optimisation (HiGHS) |
| 4 | `Rounder.round` | Floor to integer cycles + greedy top-up |
| 5 | `ScheduleBuilder.build` | Insert changeovers/cleanings, split into shifts |
| 6 | `ExcelExporter.export` | Render the five-sheet workbook |

Orchestration lives in `JK_LP_Curing_Scheduler_v2.run`.

---

## 4. Data inputs

| Dataset | Loader | Granularity | Key columns |
|---|---|---|---|
| **Demand** | `ETL.load_demand` | per active PCR SKU | `SKUCode`, `Quantity`, `Priority` |
| **Cycle times** | `ETL.load_cycle_times` | cycle-time master | `SKUCode`, `CycleTime_min` |
| **Machine allowable** | `ETL.load_machine_allowable` | SKU → allowable presses | `SKUCode`, `Machines` (list of press IDs) |
| **GT inventory** | `ETL.load_gt_inventory` | per SKU | `SKUCode`, `GT_Inventory` |
| **Running moulds** | `ETL.load_running_moulds` | up to **170** presses | `Machine`, `SKUCode`, `MouldNos`, `MouldLife_remaining`, `Num_Moulds` |
| **Mould master** | `ETL.load_mould_master` | full mould pool | `MouldNo`, `Matl.Code` (SKU), `Active Flag` |

Each loader has a `*_from_excel` twin so the whole pipeline can run without a
database connection.

**Cycle-time transformation** (raw cure time → effective press minutes):

```
CycleTime_min = round( (Raw_CureTime + LOAD_UNLOAD_BUFFER_MIN) / PRESS_EFFICIENCY )
              = round( (Raw + 2.3) / 0.90 )
```

This inflates the raw cure time by the per-cycle load/unload handling buffer and
the press efficiency derate, so one "minute" in the model is a realistic press
minute.

---

## 5. The LP formulation

The core optimisation (`LP_Solver.solve`) is a **continuous linear program**
over press-minutes, solved with HiGHS.

**Decision variables**
- `x[s, m]` — minutes of press *m* devoted to SKU *s* (continuous, ≥ 0)
- `u[s]` — unmet demand-minutes for SKU *s* (slack, continuous, ≥ 0)

**Objective** — minimise unmet demand first, changeovers second:

```
minimise   Σ_s u[s]                                  (primary: unmet demand-mins)
         + CHANGEOVER_PENALTY_WEIGHT · Σ_s,m x[s,m] / Demand_Mins[s]
                                                     (secondary: spread penalty)
```

The tiny second term (weight `0.01`) gently discourages smearing a SKU across
many presses, which keeps changeover count down without ever trading away demand
fulfilment.

**Constraints**
- **Press capacity** — for each press *m*: `Σ_s x[s,m] ≤ available_mins − locked_mins[m]`
- **Demand satisfaction** — for each SKU *s*: `Σ_m x[s,m] + u[s] ≥ Demand_Mins[s]`
- **Eligibility bounds** — `x[s,m]` is forced to `0` unless press *m* is
  allowable for SKU *s* **and** the mould tracker deems it eligible
  (see [§8](#8-mould-tracking--eligibility)).

`available_mins = PLANNING_DAYS × SHIFTS_PER_DAY × HOURS_PER_SHIFT × 60`.
`locked_mins[m]` is the time already committed by continuity blocks ([§7](#7-continuity-blocks)).

---

## 6. Rounding & top-up

The LP returns fractional minutes; presses run whole cure cycles, so
`Rounder.round` converts the solution to integers:

1. **Floor pass** — each `x[s,m]` becomes `floor(minutes / cycle_time)` cycles.
2. **Accurate per-SKU changeover charging (v4 fix)** — walk each press's SKU
   list in priority order and charge a changeover **only for SKUs actually
   kept** on that press. Earlier versions reserved CO budget up front for every
   SKU and never refunded it when a SKU was trimmed, silently wasting capacity.
3. **Greedy top-up** — flooring always under-produces; a priority-sorted top-up
   pass fills residual press capacity to close rounding gaps, accounting for the
   changeover cost of each added SKU.

Each unit = `CAVITIES_PER_MOULD × MOULDS_PER_PRESS` per cure cycle.

---

## 7. Continuity blocks

Before the LP runs, `_build_continuity` inspects the **running-moulds** dataset
(what each press is producing *right now*). If a press is already curing a SKU
that still has open demand, the scheduler **keeps it running that SKU** rather
than forcing an unnecessary changeover at the start of the horizon.

For each such press it:
- emits **continuity production rows** from the plan start,
- inserts **mould-cleaning** rows at the right cumulative-unit boundaries,
- **locks** those minutes out of the LP's capacity (`locked_mins`),
- subtracts the continuity-produced units from that SKU's LP demand, and
- records the press's last SKU so the rounder/builder don't insert a phantom
  changeover when the LP keeps the same SKU on that press.

This both saves changeovers and reflects real plant state on day one.

---

## 8. Mould tracking & eligibility

`MouldTracker` is the in-memory ledger of every active mould: which SKUs it fits,
its remaining life, and which press (if any) it's currently locked to.

A press is eligible for a SKU only if the SKU is physically allowable on it **and**
enough compatible moulds exist. Two policies (toggle `PERMISSIVE_MOULD_ELIGIBILITY`):

| Policy | Rule | Effect |
|---|---|---|
| **Permissive** (default) | Need `≥ MOULDS_PER_PRESS` **total** compatible moulds (free *or* locked) | Idle presses can be used even if the SKU's moulds are currently on another press — assumes moulds can be moved manually |
| **Strict** | Need `≥ MOULDS_PER_PRESS` **free** moulds in the global pool | Conservative; never assumes a physical mould move |

Continuity presses are always whitelisted regardless of policy.

---

## 9. Output workbook

`ExcelExporter` writes one formatted `.xlsx` (name from `Config.OUTPUT_FILE`)
with five sheets. A KPI banner (demand, planned, gap, fulfilment %, avg
utilisation, changeovers, cleanings) sits atop every sheet.

| Sheet | Contents |
|---|---|
| **Demand Fulfillment** | Per-SKU demand vs planned, gap, fulfilment %, status (FULLY MET / PARTIAL / UNMET / UNSCHEDULABLE) |
| **Machine Schedule** | Per-press SKU assignment: cycles, units, minutes, days used |
| **Shift Schedule** | Row-level, shift-wise plan with `StartTime`/`EndTime`, `CHANGEOVER` and `MOULD_CLEAN` rows — **this is the base curing schedule** downstream logic consumes |
| **Machine Utilization** | Per-press used / idle minutes, utilisation %, SKU count |
| **Mould Tracker** | Each mould: compatible SKUs, life remaining, assigned press |

The **Shift Schedule** sheet (header on row 3) is the canonical hand-off
artefact — every freezing / simulation step keys off its `Date`, `Shift`,
`Machine`, `SKUCode`, and `Qty` columns.

---

## 10. Configuration reference

All knobs live in the `Config` class at the top of the file. **Current BTP values:**

| Setting | Value | Meaning |
|---|---|---|
| `DB_NAME` | `jkplanningV1` | MySQL planning database (BTP) |
| `PLANNING_DAYS` | `31` | Horizon length in days |
| `SHIFTS_PER_DAY` | `3` | Shifts A / B / C |
| `HOURS_PER_SHIFT` | `8` | Hours per shift |
| `SHIFT_START_HOUR` | `7` | Shift A starts 07:00 |
| `CAVITIES_PER_MOULD` | `2` | Tyres produced per mould per cycle |
| `MOULDS_PER_PRESS` | `2` | Moulds mounted on one press |
| `NEW_MOULD_LIFE` | `3000` | Cures before a mould needs cleaning |
| `CHANGEOVER_DURATION_MIN` | `300` | Minutes lost per SKU switch (**BTP**) |
| `CLEANING_DURATION_MIN` | `120` | Minutes lost per mould cleaning (**BTP**) |
| `LOAD_UNLOAD_BUFFER_MIN` | `2.3` | Per-cycle handling buffer |
| `PRESS_EFFICIENCY` | `0.9` | Press efficiency derate |
| `MAX_CHANGEOVERS_PER_SHIFT` | `5` | Changeover throttle per shift (**BTP**) |
| `CHANGEOVER_PENALTY_WEIGHT` | `0.01` | Secondary objective weight |
| `PERMISSIVE_MOULD_ELIGIBILITY` | `True` | Mould-eligibility policy ([§8](#8-mould-tracking--eligibility)) |
| `PLAN_DATE` | `2026-05-01 07:00` | Plan start timestamp |
| `OUTPUT_FILE` | `BTP_PCR_Curing_LP_v4_PlanSchedule_…xlsx` | Output workbook name |

> These are the **BTP plant** constants. The CTP plant uses different downtime
> values (360 min changeover, 180 min cleaning, 3 changeovers/shift, 30-day
> horizon) — that's the only material difference between the plant variants.

---

## 11. Code map

`jk_curing_lp_PCR.py` (single file, ~1,580 lines):

| Section | Lines (approx.) | Role |
|---|---|---|
| `Config` | 72–120 | All tunable constants |
| `MouldTracker` | 126–275 | Mould ledger + eligibility policy |
| `ETL` | 277–445 | DB **and** Excel loaders for all six datasets |
| `LP_Solver` | 447–543 | Builds & solves the continuous LP (Phase 3) |
| `Rounder` | 545–723 | Integer rounding + greedy top-up (Phase 4) |
| `ScheduleBuilder` | 725–925 | Changeover/cleaning insertion, shift splitting (Phase 5) |
| `JK_LP_Curing_Scheduler_v2` | 927–1308 | Orchestrator: continuity, prep, run, summaries |
| `ExcelExporter` | 1310–1478 | Five-sheet formatted workbook (Phase 6) |
| Helpers | 1480–1519 | `con_split_into_shifts`, `_get_shift_fn` |
| Entry points | 1521–1584 | `run_from_excel`, `run_from_database`, `__main__` |

---

## 12. Assumptions & limitations

- **Solve-then-round, not exact MILP.** The continuous LP is globally optimal in
  press-minutes, but integer rounding + greedy top-up can leave the final
  integer plan slightly sub-optimal vs a full mixed-integer formulation. The
  trade-off buys a fast, reliable solve at plant scale.
- **Changeovers are modelled as a budgeted cost, not an exact sequencing
  constraint.** `MAX_CHANGEOVERS_PER_SHIFT` throttles how many changeovers land
  in any one shift during layout; the LP itself only penalises spreading.
- **Permissive eligibility assumes moulds can be physically relocated** between
  compatible presses. Set `PERMISSIVE_MOULD_ELIGIBILITY = False` if that's not
  operationally true.
- **Database credentials are hard-coded in `Config`.** Override them (or use the
  Excel entry point) before sharing or deploying outside the plant network.

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **SKU** | A specific tyre size/spec (`SKUCode`) |
| **Press / Machine** | A curing press; identified by a numeric ID |
| **Mould** | Tooling mounted on a press; each fits a set of SKUs and has a finite life |
| **Cycle / Cure** | One curing run of a press; yields `CAVITIES_PER_MOULD × MOULDS_PER_PRESS` tyres |
| **Changeover (CO)** | Switching a press from one SKU to another; costs `CHANGEOVER_DURATION_MIN` |
| **Continuity** | Keeping a press on the SKU it's already running to avoid a startup changeover |
| **Top-up** | Greedy post-rounding pass that fills residual capacity to close rounding gaps |
| **GT inventory** | Green-tyre (uncured) inventory available as input stock |

---

*Designed by Paranjay Dodiya — Algo8 AI Pvt. Ltd. for JK Tyre & Industries Ltd.
(Banmore Tyre Plant). v4 — Production.*
