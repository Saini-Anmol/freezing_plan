# Technical Requirements Document — Freezing Plan Simulation

**Project:** Freezing Plan Simulation for PCR Curing Schedule
**Companion to:** [`PRD.md`](PRD.md)
**Sibling repo (LP source, treated as black box):** [`../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py`](../../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py)

---

## 1. System overview

The wrapper is a Python CLI that:
1. Loads the existing PCR LP scheduler as a library
2. Drives a 30-day rolling-horizon simulation across 20–30 days
3. Maintains state across daily iterations (open demand, mould assignments, cumulative actuals)
4. Applies CTP revisions on configured days
5. Generates an end-of-study Excel KPI report

It does **not** modify the LP source. The LP is invoked through a single thin adapter ([`V1/utilities/lp_adapter.py`](../V1/utilities/lp_adapter.py)).

```
┌──────────────────────────────────────────────────────────────────────┐
│                              main.py                                  │
│            (only entry point — flags: --reset, --smoke-test,          │
│             --refresh-masters)                                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ simulation_route.run │  ← end-to-end driver
                    └──────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────────┐
       ▼                       ▼                           ▼
┌─────────────┐      ┌──────────────────┐         ┌─────────────────┐
│ master_data │      │  daily_route +   │         │ kpi_excel_writer│
│  (DB pull / │      │  revision_route  │ ◄───┐   └─────────────────┘
│   cache)    │      └──────────────────┘     │
└─────────────┘              │                │ history dict
                             ▼                │
                ┌────────────────────────┐   │
                │ lp_adapter.run_lp()    │   │
                │  ↓                     │   │
                │ JK_LP_Curing_Scheduler │   │
                │ _v2.run()              │   │
                └────────────────────────┘   │
                             │                │
                             ▼                │
                ┌────────────────────────┐   │
                │ Day-N daily_route:     │   │
                │  · extract today's     │   │
                │    production          │   │
                │  · simulate actuals    │   │
                │  · decrement demand    │   │
                │  · roll moulds         │   │
                │  · archive day        ─┼───┘
                └────────────────────────┘
```

## 2. Stack

| Component | Choice | Reason |
|---|---|---|
| Language | Python 3.10+ | Matches the LP source |
| Numerics | numpy, pandas, scipy | Same as LP |
| Excel I/O | openpyxl | Same as LP |
| Config | PyYAML | Human-edit-friendly; same one-file philosophy as LP's `Config` class |
| DB | sqlalchemy + pymysql | Reuses LP's existing connection pattern |
| Solver | HiGHS (via scipy.optimize.linprog) | Inherited from LP |

**Dependencies file:** [`requirements.txt`](../requirements.txt).

## 3. Repository layout

```
freezing_simulation/
├── main.py                    only entry point
├── config.yaml                runtime config (paths, dates, seed, factor band)
├── requirements.txt
├── CLAUDE.md                  AI-agent guide (working knowledge)
├── docs/
│   ├── PRD.md                 product requirements (this doc's companion)
│   └── TRD.md                 (this doc)
├── inputs/                    user-provided + DB-cached masters
│   ├── Apr_CTP_PCR_Requirement.xlsx     CTP demand workbook
│   ├── daily_moulds_pcr_*.csv           Day-1 running moulds
│   └── masters/                          DB-cached LP master tables
├── state/                     auto-managed simulation state (CSV files)
├── runs/                      per-day audit archive
├── outputs/                   final KPI workbook + ideal baseline + summary
└── V1/                        modular code
    ├── config/                config loader + path resolver
    ├── setups/                ETL: master_data, input_loader, state_initializer
    ├── utilities/             lp_adapter, state_io, actuals_simulator,
    │                          demand_manager, moulds_manager, archiver
    ├── routes/                daily_route, revision_route, simulation_route
    └── reports/               kpi_calculator, stability_tracker, kpi_excel_writer
```

## 4. Module reference

### 4.1 `config/settings.py`
- `load_config(plant="ctp", path=None) → dict` — reads `configs/<plant>.yaml`, resolves all paths to absolute `Path` objects, parses `start_date` to `datetime.date`, builds `revision_by_day = {day_idx: sheet_name}` map. **Mutates** module-level path constants `MASTERS, STATE, RUNS, OUTPUTS` to point under that plant's subfolder.
- `add_lp_to_path(lp_path)` — prepends `lp_module_path` to `sys.path` so `from jk_curing_lp_PCR import …` works.
- `ensure_dirs()` — `mkdir -p` for currently scoped `INPUTS, MASTERS, STATE, RUNS, OUTPUTS`.
- Module constants: `ROOT, INPUTS, MASTERS, STATE, RUNS, OUTPUTS`.

**Important:** other modules MUST access these as `settings.STATE` etc. (attribute on the module), not via `from V1.config.settings import STATE` — the import-time copy would not see the plant-scoping update done by `load_config`.

### 4.2 `setups/master_data.py`
- `cache_complete() → bool` — true iff all 4 master Excel files exist in `inputs/masters/`.
- `refresh(cfg, force=False)` — if cache missing or `force=True`, opens MySQL via SQLAlchemy using `Config.DB_*` from the LP's Config class, calls `ETL.load_cycle_times/load_machine_allowable/load_gt_inventory/load_mould_master`, writes each result as `cycle_times.xlsx, machine_allowable.xlsx, gt_inventory.xlsx, mould_master.xlsx`.
- `load() → dict[str, pd.DataFrame]` — reads cached files; returns `{cycles, allowable, gt, mould_master}`. Parses the `Machines` column from string-serialised lists back to Python lists via `ast.literal_eval`.

### 4.3 `setups/input_loader.py`
- `load_demand_sheet(ctp_file, sheet_name) → DataFrame` — reads one CTP sheet, renames `Updated_Requirement→Quantity, ConsolidatedPriorityScore→Priority`, drops zero-qty rows, casts `Quantity` to int.
- `load_day1_moulds(moulds_file, target_life=3000) → DataFrame` — reads the daily moulds CSV. **Critical conversion:** `df["Mould life"] = (target_life - df["Mould life"]).clip(lower=0)` (consumed → remaining). Splits `Current MouldNo` on `#` into LH/RH, groups by `WCNAME` to one row per machine with `MouldNos` as a list, `MouldLife_remaining = min(LH_life, RH_life)`. Output columns: `Machine, SKUCode, MouldNos, MouldLife_remaining, Num_Moulds`.

### 4.4 `setups/state_initializer.py`
- `initialise(df_base_demand, df_day1_moulds, start_date)` — first-time creation of all state CSVs from the user-provided inputs. Persists `original_plan, baseline_plan, open_demand, cumulative_actuals, running_moulds, sim_meta`.
- `state_already_initialised() → bool` — used by `simulation_route` to decide between fresh init vs. resume.

### 4.5 `utilities/lp_adapter.py`
- Single function: `run_lp(df_demand, df_cycles, df_allow, df_gt, df_mould_master, df_running, plan_start, planning_days, lp_module_path) → dict`
- Sets `LPConfig.PLANNING_DAYS = planning_days` and `LPConfig.PLAN_DATE = plan_start` per call (so the same loaded LP can be reused across days).
- Constructs a fresh `MouldTracker`, calls `JK_LP_Curing_Scheduler_v2().run(...)`, returns the LP's `dict` of 5 result DataFrames.

### 4.6 `utilities/state_io.py`
- `write_state(name, df)` — writes to a tempfile in `state/` then `os.replace`s atomically.
- `read_state(name) → DataFrame` — reads `state/{name}.csv`.
- `state_exists(name) → bool`.
- `clear_state()` — removes all CSVs in `state/`. Called by `--reset`.

### 4.7 `utilities/actuals_simulator.py`
- `make_rng(seed) → np.random.Generator` — wraps `np.random.default_rng`.
- `draw_factors(skus, low_pct, high_pct, rng) → dict[str, float]` — one independent uniform draw per SKU per call.
- `apply_to_scheduled(scheduled_df, factors) → DataFrame` — adds `factor` and `Actual_Qty = round(Qty × (1 + factor)).clip(lower=0).astype(int)` columns.

### 4.8 `utilities/demand_manager.py`
- `build_demand_for_lp() → DataFrame` — reads `open_demand.csv`, drops zero-qty SKUs, returns a clean `[SKUCode, Quantity, Priority]` for the LP.
- `decrement_open_demand(actuals_by_sku) → DataFrame` — clip-at-zero subtraction; updates both `open_demand.csv` and `cumulative_actuals.csv`.
- `apply_revision(revised_df) → DataFrame` — implements: `new_open_balance = revised_qty − cumulative_actuals` per SKU; new SKUs get full revised qty; SKUs in baseline but absent from revision are kept at their current open balance with a logged warning. Updates `baseline_plan.csv`.

### 4.9 `utilities/moulds_manager.py`
- `load_running_moulds_for_lp() → DataFrame` — reads state, parses `MouldNos` from "|"-joined string back to list.
- `roll(df_shift_today, open_demand_after, actuals_factors, df_mould_master, df_allow, df_cycles, day_idx, simulation_days, target_life, consolidation_enabled, consolidation_single_press_threshold, consolidation_slack) → (DataFrame, list[dict])` — for every machine in current `running_moulds`:
    - If today produced rows and `open_demand_after[last_sku] > 0` (still has demand): keep the mount, decrement mould life by `actual_units / 2` (or `target_life − post_clean_units / 2` if a clean happened today). `last_sku` is the chronologically-last production block.
    - Otherwise the press is **available**: it produced nothing today, OR its `last_sku` open balance hit 0.
    - **Tail-consolidation (`consolidation_enabled=True`, default):** for each SKU with open demand, `min_presses = max(1, ceil((open/2 · CycleTime_min) / ((simulation_days − day_idx)·24·60 · consolidation_slack)))`, capped at the compatible-press count from `df_allow`; if `open < consolidation_single_press_threshold` then `min_presses = 1`. `deficit = max(0, min_presses − #still-running presses on that SKU)`. Walking SKUs by descending `ConsolidatedPriorityScore`, assign up to `deficit` available presses compatible with the SKU, preferring presses whose mounted mould pair is already valid for the new SKU (keep pair + life; else fresh pair from `df_mould_master`, life `target_life`). Each assignment logs a forced rotation `{Machine, From_SKU, To_SKU}`. Unassigned available presses are dropped (idle). On the last day's roll (`day_idx == simulation_days`) no re-assignment is done.
    - **Legacy (`consolidation_enabled=False`):** idle presses keep their mount; a press whose `last_sku` finished force-mounts the highest-priority compatible unmet SKU (`df_allow` + `open_demand_after`, fresh life/pair) — only dropped if no candidate.
- Returns `(new_running_moulds_df, forced_rotations_list)`. Knobs come from `configs/<plant>.yaml` via `cfg` in `daily_route.run_one_day`.

### 4.10 `utilities/archiver.py`
- `archive_day(day_date, day_idx, lp_results, today_actuals_df, factors, open_after)` — writes per-day artefacts to `runs/YYYY-MM-DD/`: LP shift schedule (full 30-day), demand fulfillment, machine utilization, today's actuals (with factor column), open balance after, the factor JSON map, and a one-line `summary.json`.

### 4.11 `routes/daily_route.py`
- `run_one_day(day_idx, day_date, cfg, masters, rng) → dict` — the per-day orchestrator. Flow:
    1. `demand_manager.build_demand_for_lp()` (skip if empty)
    2. `moulds_manager.load_running_moulds_for_lp()`
    3. `lp_adapter.run_lp(plan_start = today @ 07:00, planning_days = 30, …)`
    4. Filter `lp_results["shift_schedule"]` to today's date AND `SKUCode not in [CHANGEOVER, MOULD_CLEAN]` → `today_prod`
    5. `actuals_simulator.draw_factors` + `apply_to_scheduled` → `actuals` DataFrame with both `Qty` and `Actual_Qty`
    6. `demand_manager.decrement_open_demand(sum of Actual_Qty per SKU)`
    7. `moulds_manager.roll(...)` — captures forced rotations; appends to cumulative `state/forced_changeovers_log.csv`
    8. `archiver.archive_day(...)`
    9. Returns summary: `{day_idx, day_date, today_scheduled, today_actual, open_after, forced_rotations, lp_results, today_prod, today_actuals}`

### 4.12 `routes/revision_route.py`
- `apply(day_idx, sheet_name, cfg)` — reads the revision sheet via `input_loader.load_demand_sheet`, hands to `demand_manager.apply_revision`. Called by `simulation_route` BEFORE that day's `run_one_day`.

### 4.13 `routes/simulation_route.py`
- `_save_ideal_baseline(cfg, masters)` — runs the LP once on Day-1 inputs (pristine state), persists 5 CSVs under `outputs/ideal_baseline/`.
- `run(cfg, masters) → dict` — driver:
    1. If state not initialised, call `state_initializer.initialise`
    2. Capture ideal baseline (one-shot 30-day LP)
    3. Build `rng = actuals_simulator.make_rng(cfg["random_seed"])`
    4. For `day_idx in 1..simulation_days`:
        - If `day_idx in cfg["revision_by_day"]`, call `revision_route.apply`
        - Call `daily_route.run_one_day`, append summary to `per_day` list
    5. Persist `outputs/per_day_summary.json`
    6. Return `{ideal, per_day, cfg}` (the "history" dict the report builder consumes)

### 4.14 `reports/kpi_calculator.py`
- `_demand_basis() → (latest_qty, latest_priority, original_qty)` — reads `baseline_plan.csv` for the "latest committed" demand (last applied revision; collapses a SKU listed twice to its largest stated qty) and `original_plan.csv` for the frozen Day-1 ask. SKUs dropped from the final revision keep their Day-1 ask as the latest target.
- `build_simulated_demand_fulfillment(history) → DataFrame` — per-SKU table mirroring the LP's Demand Fulfillment sheet but with `Actual_Units = cumulative simulated`. **`Demand` = latest committed quantity** (the fulfillment denominator); `Original_Demand` = Day-1 ask, reference only. Gap / `Fulfillment_Pct` / `Status` are vs `Demand`.
- `build_simulated_shift_schedule(history) → DataFrame` — concatenated daily Day-1 production, with `Scheduled_Qty, Factor_Pct, Actual_Qty` columns side-by-side.
- `build_simulated_machine_schedule(history) → DataFrame` — `Actual_Cycles, Actual_Units, Mins_Used` per `(Machine, SKUCode)`.
- `build_simulated_machine_utilization(history, planning_days) → DataFrame` — denominator = `simulation_days × 3 × 8 × 60` minutes per press.
- `count_simulated_changeovers_and_cleans(history) → (int, int)` — sums LP-Day-1 CO + wrapper-forced rotations + LP-Day-1 mould cleans.
- `build_ideal_vs_simulated_kpi(history) → DataFrame` — side-by-side metric comparison. Reports fulfillment both **vs the latest revised plan** (primary) and **vs the Day-1 original plan** (reference); SKU status counts are vs the latest revised plan for both columns (the ideal one-shot plan is re-statused against the latest ask).
- `build_per_day_history_sheet(history) → DataFrame` — daily log including `Forced_Rotations` count.
- `load_forced_changeovers_log() → DataFrame` — reads `state/forced_changeovers_log.csv` if present.
- `build_changeover_breakdown(history) → DataFrame` — per-day breakdown of LP-scheduled vs wrapper-forced CO.

### 4.15 `reports/stability_tracker.py`
- `build(history) → DataFrame` — for each consecutive pair of daily LP runs, compares the LP's plan for every future date against the prior day's plan for the same future date. Emits `(Day_Planned, Target_Date, SKUCode, Current_Qty, Previous_Qty, Abs_Shift)`. Excludes same-day rows (Day_Planned == Target_Date).

### 4.16 `reports/kpi_excel_writer.py`
- `write(history, output_path=None) → Path` — writes the 8-sheet workbook (10 with optional Changeover Breakdown + Forced Rotations Log when forced rotations exist). Title bars in navy, KPI banner in teal, status colour-coding, atomic via `pd.ExcelWriter` context.

## 5. Data flow per simulation day

```
state/open_demand.csv              ┐
state/running_moulds.csv           ├──► demand_manager.build_demand_for_lp
inputs/masters/*.xlsx              │    + moulds_manager.load_running_moulds_for_lp
                                   ┘            │
                                                ▼
                                  ┌──────────────────────────┐
                                  │ lp_adapter.run_lp()      │
                                  │  → 30-day shift schedule │
                                  └──────────────────────────┘
                                                │
                                                ▼ filter today + exclude CO/CLEAN
                                  ┌──────────────────────────┐
                                  │ today_prod (Qty=scheduled│
                                  └──────────────────────────┘
                                                │
                            actuals_simulator   ▼
                            ┌─────────────────────────────────┐
                            │ today_actuals                   │
                            │  Qty (sched) | factor | Actual_Qty│
                            └─────────────────────────────────┘
                                                │
                  ┌─────────────────────────────┼────────────────────────────┐
                  ▼                             ▼                            ▼
   demand_manager.decrement       moulds_manager.roll              archiver.archive_day
   (open_demand,                  (running_moulds,                 (full audit dump
    cumulative_actuals)            forced_changeovers_log)          to runs/YYYY-MM-DD/)
```

## 6. State files (schemas)

All in `state/`, all CSV, all read/written via `state_io.write_state` / `read_state`.

| File | Columns | Notes |
|---|---|---|
| `original_plan.csv` | `SKUCode, Original_Quantity, Original_Priority` | Frozen at init; carried as the `Original_Demand` reference column / "vs Original" KPI row |
| `baseline_plan.csv` | `SKUCode, Baseline_Quantity, Priority` | Rewritten on each revision (= the latest committed plan); used for next-revision delta calc **and as the fulfillment-KPI denominator** |
| `open_demand.csv` | `SKUCode, Quantity, Priority` | Decremented daily; rebuilt on each revision |
| `cumulative_actuals.csv` | `SKUCode, Cumulative_Actual` | Running total of simulated production |
| `running_moulds.csv` | `Machine, SKUCode, MouldNos, MouldLife_remaining, Num_Moulds` | `MouldNos` is "\|"-joined string in CSV; deserialised to list when loaded |
| `forced_changeovers_log.csv` | `Day_Idx, Date, Machine, From_SKU, To_SKU` | Cumulative across study |
| `sim_meta.csv` | `current_day_idx, start_date` | One row; study metadata |

## 7. LP integration contract

The LP is invoked via `lp_adapter.run_lp(df_demand, df_cycles, df_allow, df_gt, df_mould_master, df_running, plan_start, planning_days, lp_module_path)`.

**Inputs:**
- `df_demand`: `[SKUCode, Quantity, Priority]` — wrapper builds from `state/open_demand.csv`
- `df_cycles`: `[SKUCode, CycleTime_min]` — from cache
- `df_allow`: `[SKUCode, Machines (list of int)]` — from cache
- `df_gt`: `[SKUCode, GT_Inventory]` — from cache (informational)
- `df_mould_master`: `[MouldNo, Matl.Code, Active Flag]` — from cache
- `df_running`: `[Machine, SKUCode, MouldNos (list), MouldLife_remaining, Num_Moulds]`
- `plan_start`: `datetime` at 07:00 of the simulated day
- `planning_days`: `30` (always)

**Outputs (dict keys):**
- `machine_schedule`: per-(Machine, SKU) integer cycles + units
- `shift_schedule`: full 30-day shift-granular timeline (the wrapper's primary input)
- `demand_fulfillment`: per-SKU LP-planned status
- `machine_utilization`: per-press LP-projected utilization
- `mould_tracker`: end-of-LP mould assignment summary

The wrapper consumes only `shift_schedule` for daily extraction; the others are archived for audit and (Day-1's set) used as the "ideal baseline" reference.

## 8. CLI contract

```
python3 main.py [--plant ctp|btp]      full study per configs/<plant>.yaml (default ctp)
python3 main.py --plant ctp --reset            wipe that plant's state/, runs/, outputs/ then run
python3 main.py --plant btp --refresh-masters  re-pull master tables from MySQL then run
python3 main.py --plant ctp --smoke-test       load all inputs, run LP for Day 1 only
```

Flags can be combined: `python3 main.py --plant btp --reset --refresh-masters`.

**Plant scoping:** `--plant <name>` causes `settings.MASTERS / STATE / RUNS / OUTPUTS` to be re-scoped at config-load time to `<dir>/<name>/...`. Two `python3 main.py` processes with different `--plant` values do not interfere.

## 9. Performance characteristics

- **Per-day LP solve:** 3–10 sec (90 machines × 45 SKUs ≈ 4,500 LP variables)
- **Per-day total work:** ~10–20 sec (LP + extraction + actuals + demand decrement + moulds roll + archive)
- **Full 20-day study:** 3–5 min on a planner laptop
- **Master data DB pull (one-time):** 10–30 sec depending on network
- **Memory:** peak ~500 MB during LP solve (HiGHS on 4,500 vars)
- **Disk:** state files <100 KB total; per-day archive ~1–2 MB; cumulative <50 MB for a 20-day study

## 10. Configuration management

`config.yaml` is the only file users edit for typical operation. All paths are relative to `freezing_simulation/`. Keys documented inline in the file. Loaded once at start of each run.

Sensitive credentials (DB password) are inherited from `LPConfig.DB_*` in `jk_curing_lp_PCR.py`. The wrapper does not duplicate or override them.

## 11. Error handling & resilience

- **Atomic state writes** — write-temp-then-rename ensures no half-written CSVs even on crash.
- **DB unavailable on first run** — clear error from SQLAlchemy; user can still proceed with `--smoke-test` after manually populating `inputs/masters/`.
- **LP infeasibility** — propagates from the LP as `RuntimeError("LP did not converge")`. Not caught; surfaced to user.
- **Missing CTP sheets** — `pd.read_excel` raises with sheet name; user fixes the workbook or the config.
- **Missing forced changeover candidate** — wrapper logs and silently drops the press from `running_moulds` (truly nothing to assign).
- **Mid-run interruption** — re-running without `--reset` resumes from the next day (state files reflect last completed day). Use `--reset` for a clean restart.

## 12. Testing strategy

- **Smoke test mode** (`--smoke-test`) — loads all inputs and runs one LP iteration. Catches schema mismatches, DB issues, mould-life conversion bugs, sys.path problems before committing to a full run.
- **2-day end-to-end test** — every code change should pass a 2-day run before a 20-day commit. Standard pattern:
  ```python
  from V1.utilities import state_io
  state_io.clear_state()
  cfg = load_config()
  cfg['simulation_days'] = 2
  cfg['revision_by_day'] = {}
  history = simulation_route.run(cfg, masters)
  kpi_excel_writer.write(history)
  ```
- **Math validation** — Shift Schedule sheet provides row-by-row `Scheduled_Qty × (1 + Factor_Pct/100) = Actual_Qty` verifiability.
- **Reproducibility check** — same seed should produce identical KPIs across runs.

## 13. Extension points

These are the well-defined seams for future work:

| Extension | Module to modify | Contract that stays the same |
|---|---|---|
| Real shop-floor actuals feed | `V1/utilities/actuals_simulator.py` | Output: same DataFrame schema (`SKUCode, Actual_Qty, ...`) |
| TBR support | New `tyre_type` arg threaded through `master_data`, `input_loader`, `lp_adapter`; LP-side: switch to `jk_curing_lp_TBR.py` | LP adapter signature unchanged |
| Holiday calendar | `master_data` or `lp_adapter`: pre-compute `effective_planning_days = 30 − holidays` and override `LPConfig.PLANNING_DAYS` per call | Schema of all state files unchanged |
| New stability metric (vs Day-1) | Add a parallel function in `stability_tracker.py`; new sheet via `kpi_excel_writer` | Existing consecutive-day metric kept |
| Forced-CO time accounting | `moulds_manager.roll` returns extra capacity-debits map; `lp_adapter` injects into `locked_machine_mins` | LP signature unchanged |

## 14. Constraints not to violate

These are hard rules — violating them breaks correctness or operational invariants:

1. Do not modify [`jk_curing_lp_PCR.py`](../../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py); only consume via `lp_adapter`.
2. Do not lower `LPConfig.CHANGEOVER_PENALTY_WEIGHT` globally to chase utilization (per user decision; auto-rotate handles idle-press case alone).
3. Do not shrink the 30-day LP planning horizon to "speed things up".
4. Do not double-convert mould life — the consumed→remaining conversion lives only in `input_loader.load_day1_moulds`.
5. Do not include `CHANGEOVER` or `MOULD_CLEAN` rows in production sums — filter by SKUCode literal, not by Remarks.
6. Do not write directly to `state/` files; always go through `state_io`.
7. Do not assume GT inventory affects the LP — it is informational only in the current build.
