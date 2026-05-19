# Freezing Plan Simulation — PCR Curing Schedule (multi‑plant)

A monthly **curing‑schedule freeze + rolling‑horizon simulation** for JK Tyre's PCR curing operations. One Python wrapper drives plant‑specific LP schedulers (CTP and BTP), executes a 30‑/31‑day daily‑rerun simulation with mid‑month demand revisions, and produces a single Excel KPI workbook that compares the **ideal single‑shot LP plan** against the **simulated daily‑rerun result**.

> **TL;DR**
> ```bash
> cd freezing_simulation
> pip3 install -r requirements.txt
> python3 main.py --plant btp --reset                     # full study
> python3 gen_ideal_report.py --plant btp                 # ideal one-shot report
> ```

---

## Table of contents

1. [Business context](#1-business-context)
2. [Repository layout](#2-repository-layout)
3. [Quick start](#3-quick-start)
4. [Architecture — how the pieces fit](#4-architecture--how-the-pieces-fit)
5. [The simulation loop](#5-the-simulation-loop)
6. [Configuration (`configs/<plant>.yaml`)](#6-configuration-configsplantyaml)
7. [Inputs](#7-inputs)
8. [Outputs](#8-outputs)
9. [KPI methodology](#9-kpi-methodology)
10. [Tail‑consolidation policy](#10-tail-consolidation-policy)
11. [Per‑plant differences (CTP vs BTP)](#11-per-plant-differences-ctp-vs-btp)
12. [Key design decisions](#12-key-design-decisions)
13. [Common operations](#13-common-operations)
14. [Troubleshooting](#14-troubleshooting)
15. [Roadmap](#15-roadmap)
16. [Further reading](#16-further-reading)

---

## 1. Business context

**Plants in scope:** JK Tyre **CTP** and **BTP** plants — both PCR (Passenger Car Radial) curing operations.

**Demand cadence.** The planning team issues a fresh **30‑day plan three times per month** — on the 5th, 15th and 25th. Each new plan revises the previous one for a rolling 30‑day horizon. Revisions typically alter SKU quantities by **±3 %** and may add new SKUs that weren't in the previous plan.

**Plant operations.** Both plants run **24 × 7 in 3 shifts** (A 07:00–15:00 · B 15:00–23:00 · C 23:00–07:00).

| | CTP | BTP |
|---|--:|--:|
| Presses | **90** | **170** |
| Active SKUs / cycle (typical) | ~45 | ~95 |
| Monthly demand | ~430k tyres | ~720k tyres |
| Changeover cost | 360 min | 300 min |
| Mould‑clean cost | 180 min | 120 min |
| Max changeovers / shift | 3 | 5 |

**Planner objective (priority order):**
1. **Maximum demand fulfilment** — produce as much of the committed demand as possible.
2. **Maximum average press utilization** — keep presses busy on unmet demand, but not at the cost of churning changeovers when the remaining demand can already be met by the presses still running it (see [tail‑consolidation](#10-tail-consolidation-policy)).
3. **Minimum changeovers** — each mould swap costs 5–6 h of downtime + crew effort.

---

## 2. Repository layout

```
freezing_plan/
├── README.md                                   ← this file
│
├── jk-ctp-lp-scheduler-main/                   CTP plant LP source (v4)
│   ├── ctp/Curing/V1/
│   │   ├── jk_curing_lp_PCR.py                 ← the LP
│   │   ├── jk_curing_lp_PCR.v2_backup.py       ← pre-v4 backup (kept for rollback)
│   │   └── jk_curing_lp_TBR.py                 (TBR — not wired into the wrapper yet)
│   └── dashboard/app.py                        (standalone web dashboard — outside this project)
│
├── jk-btp-lp-scheduler-main/                   BTP plant LP source (v4)
│   ├── jk_curing_lp_PCR.py
│   └── README.md
│
└── freezing_simulation/                        ← THE WRAPPER (one codebase drives both plants)
    ├── main.py                                 entry point — flags: --plant ctp|btp, --reset, --smoke-test, --refresh-masters
    ├── gen_ideal_report.py                     standalone "ideal one-shot" reporter (5-sheet workbook)
    ├── requirements.txt
    ├── CLAUDE.md                               working knowledge for AI agents (kept in sync with code)
    │
    ├── configs/
    │   ├── ctp.yaml                            CTP study config
    │   └── btp.yaml                            BTP study config
    │
    ├── inputs/                                 user-provided + DB-cached, scoped per plant
    │   ├── ctp/
    │   │   ├── Apr_CTP_PCR_Requirement.xlsx    demand (Initial + 2 revision sheets)
    │   │   ├── daily_moulds_pcr_2026-04-01.csv Day-1 running moulds (raw consumed-cycle format)
    │   │   └── masters/                        auto-pulled from MySQL on first run
    │   │       ├── cycle_times.xlsx
    │   │       ├── machine_allowable.xlsx
    │   │       ├── gt_inventory.xlsx
    │   │       └── mould_master.xlsx
    │   └── btp/
    │       ├── May_BTP_Requirement.xlsx        demand (Base + 2 revision sheets)
    │       ├── daily_moulds_pcr_2026-05-01.csv Day-1 running moulds (LP-ready format)
    │       └── masters/                        same 4 tables, per-plant cache
    │
    ├── state/<plant>/                          auto-managed; never edit by hand
    │   ├── original_plan.csv                   frozen Day-1 base demand (reference)
    │   ├── baseline_plan.csv                   most-recent committed plan (= last revision) — KPI denominator
    │   ├── open_demand.csv                     current open balance per SKU
    │   ├── cumulative_actuals.csv              running total of simulated production per SKU
    │   ├── running_moulds.csv                  current mould state per machine
    │   ├── forced_changeovers_log.csv          cumulative log of wrapper-induced rotations
    │   └── sim_meta.csv                        study metadata
    │
    ├── runs/<plant>/2026-MM-DD/                per-day audit dumps (one folder per simulated day)
    │   ├── lp_shift_schedule_30day.csv
    │   ├── lp_demand_fulfillment.csv
    │   ├── lp_machine_utilization.csv
    │   ├── today_actuals.csv                   Scheduled · Factor · Actual side-by-side
    │   ├── open_demand_after.csv
    │   ├── actuals_factors.json
    │   └── summary.json
    │
    ├── outputs/<plant>/                        final artefacts per study
    │   ├── final_kpi_report.xlsx               10-sheet KPI workbook
    │   ├── ideal_curing_schedule_<N>days.xlsx  5-sheet ideal one-shot report (from gen_ideal_report.py)
    │   ├── ideal_baseline/                     5 CSVs from the one-shot 30-/31-day LP run
    │   └── per_day_summary.json
    │
    ├── docs/
    │   ├── PRD.md                              product requirements
    │   └── TRD.md                              technical requirements
    │
    └── V1/                                     modular wrapper code (plant-agnostic)
        ├── config/settings.py                  loads configs/<plant>.yaml; scopes paths per-plant
        ├── setups/
        │   ├── master_data.py                  MySQL pull + cache reload of LP master tables
        │   ├── input_loader.py                 demand sheets + Day-1 moulds (consumed → remaining)
        │   └── state_initializer.py            first-time creation of state/<plant>/ files
        ├── utilities/
        │   ├── lp_adapter.py                   wraps JK_LP_Curing_Scheduler_v2.run()
        │   ├── state_io.py                     atomic read/write of state CSVs
        │   ├── actuals_simulator.py            draws ±5%/+2% factor per SKU per day
        │   ├── demand_manager.py               build LP demand · decrement · apply revisions
        │   ├── moulds_manager.py               daily mould-state roll WITH the tail-consolidation policy
        │   └── archiver.py                     per-day audit dump under runs/<plant>/
        ├── routes/
        │   ├── daily_route.py                  one full day of the simulation
        │   ├── revision_route.py               applies a revision before that day's daily run
        │   └── simulation_route.py             end-to-end driver
        └── reports/
            ├── kpi_calculator.py               builds simulated counterparts of the LP's 5 sheets
            ├── stability_tracker.py            plan-vs-plan nervousness metric
            └── kpi_excel_writer.py             writes the 10-sheet workbook (banners, colours, format)
```

---

## 3. Quick start

```bash
cd freezing_simulation
pip3 install -r requirements.txt        # one-time, ~30 seconds
```

**First run (MySQL must be reachable on `35.208.174.2` for the master pull):**
```bash
python3 main.py --plant btp --reset     # full study; pulls + caches BTP masters from DB on first run
python3 main.py --plant ctp --reset     # CTP equivalent
```

**Subsequent runs (everything off the cached masters — no DB needed):**
```bash
python3 main.py --plant btp --reset
```

**Just the ideal 30‑/31‑day one‑shot schedule (no daily rerun, ~20 s):**
```bash
python3 gen_ideal_report.py --plant btp       # writes outputs/btp/ideal_curing_schedule_<N>days.xlsx
python3 gen_ideal_report.py --plant btp --refresh-masters    # also re-pull masters from DB
```

**Sanity check:**
```bash
python3 main.py --plant btp --smoke-test      # loads inputs, runs the LP for Day 1, prints summary; ~10–30 s
```

`main.py` is the **only** entry point. The `--plant` flag selects the config and scopes all `state/<plant>/`, `runs/<plant>/`, `outputs/<plant>/` paths per plant — running `--plant ctp` cannot affect a `--plant btp` study and vice versa.

---

## 4. Architecture — how the pieces fit

```
                      ┌──────────────────────────┐
                      │       main.py            │ entry point
                      └────────────┬─────────────┘
                                   │
                                   ▼
                      ┌──────────────────────────┐
                      │  V1.routes.               │ end-to-end driver
                      │  simulation_route.run     │ • capture ideal one-shot
                      └────────────┬─────────────┘ • loop day 1..N
                                   │                • write final report
                                   ▼
                      ┌──────────────────────────┐
                      │  V1.routes.               │ one simulated day
                      │  daily_route.run_one_day  │ • build_demand_for_lp
                      │                           │ • run_lp (planning_days)
                      └─────┬───────┬───────┬─────┘ • extract today's production
                            │       │       │       • apply ±5%/+2% actuals
                            ▼       ▼       ▼       • decrement open_demand
                ┌─────────────┐ ┌──────────────────┐• ROLL moulds (consolidation)
                │ lp_adapter  │ │  moulds_manager  │• archive day
                │ .run_lp()   │ │   .roll()        │
                └──────┬──────┘ └──────────────────┘
                       │
                       ▼
        ┌──────────────────────────────────────────┐
        │  jk_curing_lp_PCR.py  (plant LP, v4)     │ black-box LP
        │  ScheduleBuilder · Rounder · LP_Solver   │ • Phase 1: prep SKUs
        │  ExcelExporter · MouldTracker (perm.)    │ • Phase 2: continuity blocks
        └──────────────────────────────────────────┘ • Phase 3: HiGHS solve
                                                     • Phase 4: round to cycles
                                                     • Phase 5: shift schedule
```

The LP plans 30 (or 31) days at a time but **only Day‑1 is executed** each iteration — the next 29 days are discarded and re‑planned tomorrow. The wrapper carries state (open demand, mould assignments, cumulative actuals) across days so each day's LP starts from a refreshed reality.

**Two‑layer separation of concerns:**

- The **LP layer** (`jk-*-lp-scheduler-main/jk_curing_lp_PCR.py`, v4) is a black box that returns a 30‑day plan given today's demand + running moulds. It's **never modified at runtime by the wrapper** — only `Config.PLANNING_DAYS` and `Config.PLAN_DATE` are set in memory before each call. The LP source itself was edited only twice in this project: to back‑port the v4 fixes from BTP to CTP, and to guard against `n_vars == 0` (empty‑LP edge case).
- The **wrapper** (`freezing_simulation/V1/`) is plant‑agnostic. It does state, revisions, actuals simulation, mould rolling, the tail‑consolidation policy, and KPI reporting. One code path drives both plants; the plant is selected at runtime via `--plant`.

---

## 5. The simulation loop

```text
1. INIT (once, on first --reset run for a plant)
   ─ state_initializer.initialise(base_demand, day1_moulds, start_date)
   ─ writes state/<plant>/{original_plan, baseline_plan, open_demand,
                            cumulative_actuals, running_moulds, sim_meta}.csv

2. IDEAL BASELINE (once per run)
   ─ simulation_route._save_ideal_baseline(cfg, masters)
   ─ runs the LP once on the pristine Day-1 base demand for the full horizon
   ─ writes outputs/<plant>/ideal_baseline/{shift_schedule, demand_fulfillment,
                                              machine_utilization, machine_schedule,
                                              mould_tracker}.csv

3. DAILY LOOP  (day_idx = 1 .. simulation_days)
   For each day:
     a) IF day_idx ∈ revision_days:
            revision_route.apply(day_idx, revision_sheet, cfg)
            → demand_manager.apply_revision(revised_df)
                · for each SKU in revised sheet:
                    new_open_balance = revised_qty − cumulative_actuals[sku]
                · adds new SKUs at full revised qty
                · rewrites baseline_plan = revised sheet (= new KPI denominator)

     b) daily_route.run_one_day(day_idx, day_date, cfg, masters, rng):
          ─ df_demand = demand_manager.build_demand_for_lp()
          ─ df_running = moulds_manager.load_running_moulds_for_lp()
          ─ lp_results = lp_adapter.run_lp(df_demand, …)        ← LP plans 30/31 days
          ─ today_prod = filter LP shift_schedule to Day-1 production rows
          ─ factors = actuals_simulator.draw_factors(SKUs, -5%, +2%, rng)
          ─ actuals = today_prod × (1 + factor_per_sku)         ← the "simulated reality"
          ─ demand_manager.decrement_open_demand(actuals)
          ─ moulds_manager.roll(today_shift, open_after, factors, masters, …)
                                                                ← tail-consolidation pass
                                                                  (see §10)
          ─ archiver.archive_day(day_date, …)

4. REPORT
   ─ kpi_excel_writer.write(history) → outputs/<plant>/final_kpi_report.xlsx
```

The actuals simulator is the only source of "real" production — there's no shop‑floor feed yet. Each day each SKU gets a single independent draw in `[−5 %, +2 %]` (mean ≈ −1.5 %), applied to every machine producing that SKU that day. Random seed is fixed (default `42`) so A/B comparisons are reproducible.

---

## 6. Configuration (`configs/<plant>.yaml`)

Same schema in both `btp.yaml` and `ctp.yaml`; values differ per plant.

| Key | BTP | CTP | Purpose |
|---|---|---|---|
| `plant` | `btp` | `ctp` | Plant identifier; must match the folder names under `inputs/`, `state/`, etc. |
| `start_date` | `2026-05-01` | `2026-04-01` | First simulated day |
| `simulation_days` | `31` | `30` | Number of daily iterations |
| `planning_days` | `31` | `30` | LP horizon per daily run (the wrapper overrides `LPConfig.PLANNING_DAYS` to this value) |
| `shift_start_hour` | `7` | `7` | Shift A starts at 07:00 (matches LP) |
| `demand_file` | `inputs/btp/May_BTP_Requirement.xlsx` | `inputs/ctp/Apr_CTP_PCR_Requirement.xlsx` | Demand workbook path |
| `base_demand_sheet` | `Base demand` | `Initial demand` | Sheet name for the Day‑1 baseline |
| `revision_sheets` | day 11 / day 21 sheets | day 11 / day 21 sheets | List of `{day, sheet}` entries |
| `day1_moulds_file` | LP‑ready CSV | raw consumed‑cycle CSV | Day‑1 running moulds (auto‑detected format) |
| `target_mould_life` | `3000` | `3000` | Cycles cap; daily moulds CSV stores **consumed** cycles |
| `consolidation_enabled` | `true` | `true` | If `false` → restore the old "never idle a press" rule |
| `consolidation_single_press_threshold` | `1200` | `1200` | Remaining demand below this ⇒ 1 press suffices (shortcut) |
| `consolidation_slack` | `1` | `1` | Headroom on the min‑presses formula (1.0 = zero cushion; 0.9 = ~10 % cushion) |
| `actuals_low_pct` / `actuals_high_pct` | `-0.05` / `+0.02` | same | Random factor band per SKU per day |
| `random_seed` | `42` | `42` | Set to `null` for fresh randomness each run |
| `tyre_type` | `pcr` | `pcr` | PCR only for now (TBR not wired) |
| `lp_module_path` | `../jk-btp-lp-scheduler-main` | `../jk-ctp-lp-scheduler-main/ctp/Curing/V1` | Path to plant LP source |
| `final_report_name` | `final_kpi_report.xlsx` | same | Output workbook filename |

**Adding a new revision** (e.g. iteration‑3 lands later):
1. Add a new sheet to the demand workbook with the same column shape (`SKUCode`, `Updated_Requirement`, `ConsolidatedPriorityScore`, …).
2. Append to `revision_sheets:` in the config.
3. `python3 main.py --plant <plant> --reset`.

---

## 7. Inputs

### 7.1 Demand workbook

Three (or more) sheets — `Initial demand` / `Base demand` for Day‑1, plus one sheet per revision (typical days: 11, 21).

| Column | Type | Use |
|---|---|---|
| `SKUCode` | str | SAP material code |
| `Base_Requirement` | float | informational only |
| `Updated_Requirement` *(or `Requirement`)* | float | **THE demand quantity** (read as `Quantity`) |
| `Order_Type` | str | informational only |
| `ConsolidatedPriorityScore` *(or `PriorityScore`)* | float | the priority (read as `Priority`) |

`input_loader.load_demand_sheet` auto‑renames the two known column‑name variants and silently drops zero‑qty rows.

### 7.2 Day‑1 running moulds CSV

Two formats are auto‑detected:

- **Raw consumed‑cycle format** *(CTP)* — `WCNAME`, `Current MouldNo` (LH#RH‑joined), `Sapcode`, `Mould life`. The wrapper splits LH#RH on `#`, groups by `WCNAME` to one row per machine, and converts **consumed → remaining** as `target_life − consumed` (clipped at 0). LH/RH life uses `min(LH, RH)`.
- **LP‑ready format** *(BTP)* — `Machine`, `SKUCode`, `MouldNos` (`|`‑joined string), `MouldLife_remaining`, `Num_Moulds`. Wrapper passes through with only the string→list deserialization.

### 7.3 Master tables (auto‑pulled from MySQL, cached as Excel)

Pulled from `Config.DB_SERVER` (the LP's Config block) on first run for each plant, cached under `inputs/<plant>/masters/`. Re‑fetch with `--refresh-masters`.

| File | DB source | Columns |
|---|---|---|
| `cycle_times.xlsx` | `Master_Curing_Design_CycleTime` | `SKUCode, CycleTime_min` (computed as `(raw + 2.3) / 0.9`) |
| `machine_allowable.xlsx` | `Master_Curing_Allowable_Machines_source` | `SKUCode, Machines (list of int)` |
| `gt_inventory.xlsx` | `gt_inventory_manual` | `SKUCode, GT_Inventory` (display only — not used by LP) |
| `mould_master.xlsx` | `Master_Mapping_Mould_SKU` (Active = True) | `MouldNo, Matl.Code, Active Flag` — maps physical moulds to compatible SKUs |

---

## 8. Outputs

### 8.1 `outputs/<plant>/final_kpi_report.xlsx` — **10 sheets**

| # | Sheet | Source | What it shows |
|---|---|---|---|
| 1 | **Demand Fulfillment** | simulated cumulative | per‑SKU `Demand` (latest revised) + `Original_Demand` (Day‑1 ask) + `Actual_Units` + `Gap` + `Fulfillment_Pct` + `Status` (vs latest) + `Eligible_Machines` + `CycleTime_min`. Status cell colour‑coded (green/amber/red/grey). |
| 2 | Machine Schedule | simulated cumulative | `Actual_Cycles`, `Actual_Units`, `Mins_Used` per (Machine, SKU). |
| 3 | Shift Schedule | concatenated daily Day‑1 | every block: `Scheduled_Qty`, `Factor_Pct`, `Actual_Qty` (verifies the conversion row‑by‑row). |
| 4 | **Machine Utilization** | simulated cumulative | per‑press `Used_Mins`, `Idle_Mins`, `Utilization_Pct`, `Actual_Total_Units`. **Utilization column colour‑coded** (≥ 90 % green · 60–90 % amber · < 60 % red). |
| 5 | Mould Tracker | end‑of‑study state | final `running_moulds` snapshot. |
| 6 | **Ideal vs Simulated** | comparison | side‑by‑side KPIs: ideal single‑shot LP vs simulated daily‑rerun. Fulfilment shown **vs latest revised** [PRIMARY] **and** vs Day‑1 original. |
| 7 | Per‑Day History | per‑day | `Scheduled_Units`, `Actual_Units`, `Open_Balance_End`, `Forced_Rotations`. |
| 8 | Schedule Stability | plan‑vs‑plan | how much today's LP plan for a future date shifted from yesterday's plan for the same date. |
| 9 | Changeover Breakdown | per‑day | **LP‑scheduled** CO vs **wrapper‑forced** CO vs total. |
| 10 | Forced Rotations Log | per event | every individual wrapper‑induced press rotation (`Day_Idx`, `Date`, `Machine`, `From_SKU`, `To_SKU`). |

### 8.2 `outputs/<plant>/ideal_curing_schedule_<N>days.xlsx`

Produced by `python3 gen_ideal_report.py --plant <plant>`. The LP's **native 5‑sheet workbook** (Demand Fulfillment · Machine Schedule · Shift Schedule · Machine Utilization · Mould Tracker) for the ideal single‑shot plan only — same one the LP produces when run standalone, fully formatted with banners/colours.

### 8.3 `outputs/<plant>/ideal_baseline/*.csv`

The ideal one‑shot's 5 DataFrames as raw CSVs. Refreshed on every full study run and on every `gen_ideal_report.py` call.

### 8.4 `runs/<plant>/2026‑MM‑DD/`

Per‑day audit dumps — useful for debugging a specific day or comparing day‑on‑day plan changes.

### 8.5 `outputs/<plant>/per_day_summary.json`

One JSON entry per simulated day: `{day_idx, day_date, today_scheduled, today_actual, open_after, forced_rotations}`.

---

## 9. KPI methodology

### 9.1 Demand‑fulfilment denominator: **latest revised plan**

Fulfilment is measured against the **most recent committed demand** — i.e. the last applied revision (`state/baseline_plan.csv`). For a study with revisions on Day 11 + Day 21 that's the 2nd iterative demand; with no revisions it equals the base demand.

The frozen Day‑1 base plan (`state/original_plan.csv`) is kept as:
- the **`Original_Demand`** reference column on the *Demand Fulfilment* sheet, and
- a **"Fulfilment % vs Original Day‑1 Plan"** row on the *Ideal vs Simulated* sheet

so the apples‑to‑apples comparison with the ideal one‑shot LP (which only ever planned against the Day‑1 demand) is preserved.

### 9.2 Fulfilment %: simple **average across SKUs**, not units‑weighted

The headline fulfilment metric is the **simple arithmetic mean of per‑SKU (Actual / Demand × 100) across SKUs with positive demand.** Each SKU contributes equally regardless of size — a 4‑tyre micro‑SKU at 0 % drags the mean as much as a 50,000‑tyre SKU at 100 %. Per‑SKU percentages are **NOT capped at 100 %**, so over‑produced SKUs (e.g. 102 %) carry their full ratio into the average.

Why the change from the older units‑weighted ratio? Because the planner wanted small unmet SKUs visible in the headline — under the old metric, a 4‑tyre miss was invisible (~0.0006 % drag); under this one it's a full `1/N` of a percentage point.

### 9.3 Machine utilization: production‑minutes only

```
Utilization_Pct = sum(production EndTime − StartTime per machine) / Available_Mins × 100
Available_Mins  = simulation_days × 3 shifts × 8 h × 60
```

`CHANGEOVER` and `MOULD_CLEAN` rows are **stripped before summing**, so they fall into `Idle_Mins`. The denominator is full calendar time — nothing is deducted for changeovers/cleans. Consistent across CTP LP, BTP LP, and the wrapper's simulated version. Wrapper‑forced changeovers don't subtract their 360 min from next‑day capacity either (known modelling simplification — see [Roadmap](#15-roadmap)).

### 9.4 Changeover count

Two sources, distinguished on sheet 9 (*Changeover Breakdown*):
- **LP‑scheduled CO** — `CHANGEOVER` rows in the LP's own shift schedule (continuity‑press switches + LP‑planned mid‑month swaps).
- **Wrapper‑forced CO** — auto‑rotations performed by `moulds_manager.roll()` (now under the consolidation policy — see §10). Logged in `state/<plant>/forced_changeovers_log.csv` and surfaced on sheet 10 (*Forced Rotations Log*).

The "Total Changeovers" row on the Ideal vs Simulated sheet sums both.

---

## 10. Tail‑consolidation policy

The old rule was "**never idle a press while a compatible unmet SKU exists**" — any freed press was immediately remounted with the highest‑priority compatible unmet SKU. That fragmented small leftover demand across dozens of presses in the back half of the month (one example BTP run: SKU `1225219015008SLTB0` had 310 tyres of demand running on **25 different presses**), and the changeover count exploded at the tail.

The current rule (gated by `consolidation_enabled`): **a freed press only takes a new SKU if that SKU genuinely still needs more presses to finish on time — otherwise the press is allowed to sit idle.** A press idling for a few days at month's end costs nothing real; force‑mounting a SKU on it costs a 5–6 h changeover and crew effort.

### 10.1 Daily mechanics (in `moulds_manager.roll()`)

```text
1. Classify each press:
     • running SKU still has open demand  →  keep, no rotation
     • running SKU just finished (or already idle today)  →  available pool

2. For every SKU with open demand, compute min_presses needed to finish on time:
     work_min      = open_demand / 2 × cycle_time
     cap_per_press = days_left × 24 × 60 × slack          ← virtual budget per press
     min_presses   = max(1, ⌈work_min / cap_per_press⌉)
     min_presses   = min(min_presses, #eligible presses)
   Shortcut: if open_demand < single_press_threshold (default 1200), min_presses = 1.

3. deficit(SKU) = max(0, min_presses − presses already running it)

4. Walk SKUs in priority order (highest first). For each with deficit > 0:
     take up to `deficit` of the available presses compatible with the SKU (per df_allow).
     Among candidates, PREFER one whose currently-mounted mould pair is already
     compatible with the new SKU (no physical mould swap needed — same moulds keep
     running, just produce a different SKU). Each press claimed = one forced rotation,
     logged exactly as before in forced_changeovers_log.

5. Available presses left unassigned → dropped (left idle).
   Do NOT force a changeover just to avoid idleness.
```

**Guarantees:**
- Demand fulfilment isn't sacrificed: every SKU with open demand gets at least enough presses to finish in the time remaining (subject to compatible‑press availability and priority contention — same contention semantics as the old rule).
- Mid‑running SKUs are never interrupted — only naturally freed presses go into the pool.
- The "same moulds, different SKU" shortcut keeps mould‑life accounting honest: when moulds aren't physically swapped, life is **not** reset to 3000.

### 10.2 The three config knobs (per‑plant `<plant>.yaml`)

| Knob | Default | What it does |
|---|---|---|
| `consolidation_enabled` | `true` | Set to `false` to restore the old "never idle" rule exactly. |
| `consolidation_single_press_threshold` | `1200` | Small‑SKU shortcut: any SKU with remaining demand below this gets `min_presses = 1`. (A press can comfortably make ≤1,200 tyres in a near‑full month at typical cycle times.) |
| `consolidation_slack` | `1` | Headroom factor on the min‑presses formula. **`1.0` = zero cushion** (every press is provisioned to its full nominal remaining minutes); **`0.9` = ~10 % cushion** (slightly over‑provision — absorbs the −1.5 % actuals bias + mould‑clean overhead). Smaller slack → more presses per SKU, safer fulfilment, more changeovers. Larger slack → tighter packing, fewer presses, more risk of unmet demand. |

The slack factor is a **uniform multiplier on remaining wall‑clock minutes per press**, recomputed every day the pass runs. It is **not** a daily time slice and **not** randomised — it's notional headroom for the planner's "how many presses do I need?" decision.

### 10.3 Measured impact (BTP 31‑day study)

| Metric | Old "never idle" rule | Consolidation (slack 1) |
|---|--:|--:|
| Total changeovers | 552 | **214** |
| Wrapper‑forced changeovers alone | ~453 | ~164 |
| Avg press utilization | 87.83 % | **93.27 %** |
| Fulfilment % vs latest (units‑weighted) | 92.99 % | **99.11 %** |
| Fully met / partial / unmet SKUs | 69 / 28 / 2 | **84 / 15 / 0** |

So the consolidation roughly **halved changeovers while *raising* fulfilment and utilization** — the freed‑up changeover time goes into production instead.

---

## 11. Per‑plant differences (CTP vs BTP)

Almost everything is shared — the wrapper is plant‑agnostic and both LPs are v4 now. The *differences* are intentional plant‑operational reality, not code drift.

### 11.1 Identical for both plants (logic / policy)

- Wrapper code (`V1/`) — 100 % shared, no plant‑specific branches.
- LP version (both are v4 with `Fix 1` continuity → LP CO row insertion, `Fix 3` rounder reclaims CO budget for trimmed SKUs, `Fix 4` `PERMISSIVE_MOULD_ELIGIBILITY = True`).
- The `n_vars == 0` empty‑LP guard (added when a tail‑consolidation day left the LP with no SKUs to schedule).
- All consolidation knobs: `enabled=true`, `threshold=1200`, `slack=1`.
- KPI methodology: latest‑revised denominator, Machine‑ID dedup (so the util sheet has true 170 / 90 rows), avg‑of‑SKUs fulfilment, green/amber/red colouring.
- Master‑backed `Eligible_Machines` and `CycleTime_min` (covers revision‑added SKUs the ideal one‑shot never saw).
- Actuals factor band `[−0.05, +0.02]`, random seed `42`, `CHANGEOVER_PENALTY_WEIGHT = 0.01`.

### 11.2 Different by design (plant‑operational reality)

| Setting | CTP | BTP | Why |
|---|--:|--:|---|
| `CHANGEOVER_DURATION_MIN` | **360 min** | 300 min | CTP plant: 420 min CO + 60 min FTC check |
| `CLEANING_DURATION_MIN` | **180 min** | 120 min | CTP plant operational reality |
| `MAX_CHANGEOVERS_PER_SHIFT` | **3** | 5 | Plant policy/staffing cap |
| `DB_NAME` | `jkplanning_CTP` | `jkplanningV1` | Different DB schemas |
| `start_date · simulation_days · planning_days` | 2026‑04‑01 · 30 · 30 | 2026‑05‑01 · 31 · 31 | April vs May calendar |
| Demand workbook | `Apr_CTP_PCR_Requirement.xlsx` | `May_BTP_Requirement.xlsx` | Different inputs |
| Day‑1 moulds format | raw consumed‑cycle (90 machines) | LP‑ready (167 machines) | Different DB ETL outputs |
| Press fleet | 90 | 170 | Plant scale |
| Median eligible presses / SKU | 33 | 82 | CTP allowable matrix is far more restrictive |

CTP runs more tightly: smaller fleet, tighter allowable matrix, costlier changeovers and cleans. Demand often runs **at or above the realistic press‑hour ceiling**, so the headline fulfilment metric on CTP is structurally lower than on BTP. That's plant physics, not a wrapper deficiency.

---

## 12. Key design decisions

| # | Decision | Where to read more |
|---|---|---|
| 1 | **Mould‑life conversion in the wrapper, not the LP.** The daily moulds CSV stores **consumed** cycles. The LP's `MouldTracker` expects **remaining**. Wrapper converts in `input_loader.load_day1_moulds`. Don't double‑convert. | `V1/setups/input_loader.py` |
| 2 | **Tail‑consolidation policy** (replaces the old "never idle" rule). See [§10](#10-tail-consolidation-policy). Toggleable via `consolidation_enabled`. | `V1/utilities/moulds_manager.py` |
| 3 | **`CHANGEOVER_PENALTY_WEIGHT` stays at 0.01.** Don't globally lower it to chase utilization — the consolidation policy is the right lever now. | LP `Config` (both plants) |
| 4 | **Schedule Stability compares plan vs plan, not actuals.** Future‑day actuals don't exist (only Day‑1 of each rerun is "real"); we compare the LP's plan for a future date today vs yesterday. | `V1/reports/stability_tracker.py` |
| 5 | **Demand‑fulfilment denominator = LATEST REVISED plan** (Day‑1 original kept as reference column / row). See [§9.1](#91-demand-fulfilment-denominator-latest-revised-plan). | `V1/reports/kpi_calculator.py:_demand_basis` |
| 6 | **LP planning horizon ≥ 30.** Shorter horizons defeat the LP's continuity logic and changeover penalty. BTP runs 31 (May); CTP runs 30 (April). | `lp_adapter` overrides `LPConfig.PLANNING_DAYS` at runtime |
| 7 | **Random seed fixed for reproducibility.** Default `random_seed: 42`. Set to `null` only when intentionally measuring noise sensitivity. | `<plant>.yaml` |
| 8 | **State files use atomic write** (write‑temp‑then‑rename). A crashed run can't leave a half‑written state CSV. | `V1/utilities/state_io.py` |
| 9 | **CTP LP upgraded from v2 → v4** in‑place; pre‑upgrade backup preserved at `jk_curing_lp_PCR.v2_backup.py`. Both plants now share the same fix set. | `jk-ctp-lp-scheduler-main/ctp/Curing/V1/` |
| 10 | **`n_vars == 0` LP guard.** When continuity blocks cover all open demand on a given day, the LP has no variables; `linprog` refuses empty problems. Both v4 LPs short‑circuit and return an empty solution in that case. | Inside each LP's `LP_Solver.solve()` |
| 11 | **Fulfilment metric = simple average across SKUs** (not units‑weighted). See [§9.2](#92-fulfilment--simple-average-across-skus-not-units-weighted). | `V1/reports/kpi_calculator.py:_avg_sku_fulfilment` |
| 12 | **Eligible_Machines / CycleTime_min are read from masters**, not from the ideal one‑shot sheet — so revision‑added SKUs the ideal LP never saw still display correctly. | `V1/reports/kpi_calculator.py:build_simulated_demand_fulfillment` |

A fuller treatment with rationale lives in [`freezing_simulation/CLAUDE.md`](freezing_simulation/CLAUDE.md).

---

## 13. Common operations

```bash
cd freezing_simulation

# Full study, fresh start
python3 main.py --plant btp --reset

# Full study with fresh masters from DB
python3 main.py --plant btp --refresh-masters --reset

# Just the ideal one-shot report (no daily rerun, ~20 s)
python3 gen_ideal_report.py --plant btp
python3 gen_ideal_report.py --plant ctp --refresh-masters

# Smoke test (Day-1 LP only — no state touched, ~10 s)
python3 main.py --plant btp --smoke-test

# A/B compare two policy settings — edit the knob, --reset, re-run, diff the KPIs
# (e.g. consolidation_slack 1 vs 0.9, or consolidation_enabled true vs false)

# Resume an interrupted study (works only if state/<plant>/ is intact —
# typically you want --reset instead since the loop re-iterates day_idx 1..N)
python3 main.py --plant btp
```

Refreshing only the running moulds from the DB (one‑off, e.g. to use today's actual press state):

```bash
cd jk-btp-lp-scheduler-main
python3 -c "
from sqlalchemy import create_engine
from jk_curing_lp_PCR import Config, ETL
eng = create_engine(f'mysql+pymysql://{Config.DB_USER}:{Config.DB_PASSWORD}@{Config.DB_SERVER}/{Config.DB_NAME}')
df = ETL(eng, 'pcr').load_running_moulds()
df['MouldNos'] = df['MouldNos'].apply(lambda l: '|'.join(map(str, l)) if isinstance(l, list) else str(l))
df[['Machine','SKUCode','MouldNos','MouldLife_remaining','Num_Moulds']].to_csv(
    '../freezing_simulation/inputs/btp/daily_moulds_pcr_2026-05-01.csv', index=False)
print(f'wrote {len(df)} machines')
"
```

---

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `[Smoke OK]` but full run fails on Day N with `ValueError: c must be a 1-D array …` | Continuity blocks covered all demand → LP got 0 variables. **Fixed** by the v4 `n_vars == 0` guard (both plants). | If the guard is missing, re‑apply the patch in `LP_Solver.solve()` (described in §12, decision 10). |
| `Machine Utilization` sheet has more rows than there are presses (e.g. 238 vs 170) | Old wrapper bug — Machine column type drift across LP row variants. **Fixed** by normalising in `build_simulated_shift_schedule`. | Make sure `freezing_simulation/V1/reports/kpi_calculator.py` is current. |
| `Eligible_Machines = 0` for a revision‑added SKU in the Demand Fulfillment sheet | The ideal one‑shot didn't see that SKU, and the report code used to look there. **Fixed** by master‑backed lookup. | Make sure `simulation_route.run` puts `masters` into `history`, and `build_simulated_demand_fulfillment` reads from `history["masters"]["allowable"]`. |
| `Eligible_Machines = 0` for a SKU that *should* have eligible presses | Master cache is stale — the SKU was added to the DB after the cache was pulled. | `python3 main.py --plant <plant> --refresh-masters --reset` |
| A SKU is genuinely UNSCHEDULABLE in the report (no eligible presses anywhere) | Real data issue — the DB's `Master_Curing_Allowable_Machines_source` has no row for it. | Raise with the plant / data owner; can't be fixed in code. |
| CTP report looks much worse than BTP | Plant physics + tighter allowable matrix + harder constants. See [§11](#11-per-plant-differences-ctp-vs-btp). | Loosen `consolidation_slack` to 0.9 for CTP if the unmet count bothers you. |
| `MySQL` connection error on first run | `Config.DB_SERVER / DB_USER / DB_PASSWORD` in the LP's Config block, or network. | Verify the DB is reachable from your laptop; or run with the existing cached masters (omit `--refresh-masters`). |
| Run takes longer than expected | 31‑day runs are slower than 30‑day; consolidation pass is plant‑size‑sensitive. | Normal range: BTP ~10–15 min, CTP ~3–5 min, smoke ~20–30 s. |

---

## 15. Roadmap

| Item | Trigger / when |
|---|---|
| Subtract 360‑min forced‑changeover time from next‑day press capacity in the wrapper's model. *(Currently forced changeovers are a counter only — utilization is not debited.)* | When KPI accuracy on forced‑rotation cost matters. |
| Per‑day output cap in the wrapper (level‑load the daily LP). Would further cut tail forced changeovers by stopping the LP from front‑loading near‑term capacity. | When you want to push tail changeovers below current levels. |
| Reserved‑press carve‑out for tiny low‑priority SKUs so they don't end up UNMET under the consolidation policy. | When unmet‑SKU count itself (not just unmet tyres) is the KPI of interest. |
| TBR (truck/bus radial) support. `jk_curing_lp_TBR.py` exists in the CTP repo but isn't wired into the wrapper. Will require a `tyre_type` parameter throughout the data path. | When the scope expands beyond PCR. |
| Holiday calendar in `<plant>.yaml` + LP holiday‑aware capacity. | When a study month has holidays. |
| Replace `actuals_simulator` with a real shop‑floor data feed. | When the feed becomes available. |
| Manager‑friendly second stability metric (vs Day‑1 baseline, not just consecutive‑day deltas). | If the current per‑day stability metric proves too noisy. |
| Sensitivity sweeps over the actuals factor band. | If you need to stress‑test variance assumptions. |
| Back‑port CTP's v4 fixes into a single shared LP module (and have the two plants extend a base class) so the two `jk_curing_lp_PCR.py` files stop drifting. | When LP maintenance burden warrants it. |

---

## 16. Further reading

- **[`freezing_simulation/CLAUDE.md`](freezing_simulation/CLAUDE.md)** — working knowledge maintained for AI agents (and humans). Mirrors the design decisions and caveats in §12; kept in sync with the code.
- **[`freezing_simulation/docs/PRD.md`](freezing_simulation/docs/PRD.md)** — product requirements (what the simulation is for, from the planner's point of view).
- **[`freezing_simulation/docs/TRD.md`](freezing_simulation/docs/TRD.md)** — technical requirements (module‑by‑module reference).
- **[`jk-btp-lp-scheduler-main/README.md`](jk-btp-lp-scheduler-main/README.md)** — drop‑in instructions for the BTP LP itself.
- The LP source files (`jk_curing_lp_PCR.py` in each plant repo) have substantial top‑of‑file docstrings describing the v4 fix history (Fix 1 / Fix 3 / Fix 4) and the five‑phase pipeline.
