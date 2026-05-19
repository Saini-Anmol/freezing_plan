# Freezing Plan Simulation — PCR Curing Schedule (multi-plant)

A daily-rerun simulation wrapper around plant-specific PCR Curing LP schedulers
(currently CTP plant; BTP plant pending). The wrapper executes a rolling 30-day
horizon every day, simulates production with a small random factor, decrements
demand, rolls mould state, and produces a final 30-day KPI workbook comparing
the **ideal single-shot LP plan** against the **simulated daily-rerun result**.

> **Per-plant LP sources** (each treated as a black box, never modified):
> - CTP: [`../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py`](../jk-ctp-lp-scheduler-main/ctp/Curing/V1/jk_curing_lp_PCR.py)
> - BTP: [`../jk-btp-lp-scheduler-main/`](../jk-btp-lp-scheduler-main/) (placeholder — code dropped here when delivered)
>
> The same wrapper drives both. Plant is selected at runtime via `--plant ctp|btp`,
> which loads `configs/<plant>.yaml` and scopes all state/runs/outputs paths under
> per-plant subfolders so studies don't collide.

---

## Business context

- **Plants in scope:** JK Tyre **CTP** (currently active; v1 study running) and **BTP** (LP code pending).
- **Demand cadence:** the planning team issues a fresh **30-day plan three times per month** — on the **5th, 15th, and 25th**. Each new plan revises the previous one for a rolling 30-day horizon.
- **Revisions** typically alter SKU quantities by **±3%** and may add new SKUs that weren't in the previous plan.
- Both plants run **24×7 in 3 shifts** (A 07–15h, B 15–23h, C 23–07h) on **~90 PCR curing presses** producing **~45 active SKUs** per cycle. BTP-specific numbers will land when the BTP LP arrives.

## Objective & constraints

The user (the planner) wants the simulation to optimise for, in priority order:

1. **Maximum demand fulfillment** — produce as much of the committed demand as possible.
2. **Maximum average press utilization** — keep presses busy on unmet demand, but not at the cost of churning changeovers when the remaining demand can already be met by the presses still running it (see decision #2, tail-consolidation).
3. **Minimum changeovers** — each mould swap costs 360 min (6 hours) of downtime + crew effort.

These three are in tension when capacity is constrained and the allowable matrix is restrictive. The wrapper resolves the tension with a **tail-consolidation policy** (see decision #2): when a press's running SKU finishes, the freed press is re-assigned only to a SKU that genuinely still needs more presses to finish its remaining demand within the study horizon — otherwise the press is left idle rather than paying a changeover just to avoid idleness. This keeps fulfillment intact (every SKU with open demand still gets at least enough presses) while killing the long tail of changeovers that scattered a handful of nearly-done SKUs across dozens of presses. Do **NOT** globally lower the LP's `CHANGEOVER_PENALTY_WEIGHT` to chase utilization — the user has explicitly decided against that.

## Approach (rolling-horizon simulation)

```
For day_idx = 1..N (currently N=20 because only iter-1 revision data exists):
  IF day_idx in {revision days}:
    Apply revision:
      open_balance[sku] = revised_qty[sku] − cumulative_actuals[sku]
      priority[sku]     = revised_priority[sku]
      Add new SKUs from revision at full revised qty
  Run LP for [today, today+30) with current open_demand + running_moulds
  Extract Day-1 production rows from LP shift_schedule
  Apply per-SKU random factor in [-5%, +2%] → simulated Actual_Qty
  Decrement open_demand by Actual_Qty
  Update cumulative_actuals
  Roll running_moulds (tail-consolidation policy):
    Presses whose running SKU still has open demand → kept, no rotation.
    Presses whose SKU just finished (+ presses idle today) → "available" pool.
    For each SKU with open demand, compute the MIN presses it needs to finish
    in the time left; re-assign available presses (priority order, prefer no
    mould swap) only up to that deficit. Leftover available presses → idle.
  Archive run snapshot under runs/YYYY-MM-DD/
End loop
Build 8-sheet KPI report comparing Ideal vs Simulated
```

The LP itself optimises 30 days, but only Day-1 is "executed" each iteration — the next 29 days are discarded and re-planned tomorrow.

---

## Repository layout (multi-plant)

```
freezing_plan/
├── jk-ctp-lp-scheduler-main/      CTP plant LP source (don't modify)
│   └── ctp/Curing/V1/jk_curing_lp_PCR.py
├── jk-btp-lp-scheduler-main/      BTP plant LP source (placeholder until delivered)
│   └── README.md                  drop-in instructions
└── freezing_simulation/           ← this folder; one wrapper drives both plants
    ├── main.py                    ← THE entry point. Use --plant ctp|btp.
    ├── configs/
    │   ├── ctp.yaml               CTP study config (active)
    │   └── btp.yaml               BTP study config (template; finalize when BTP LP lands)
    ├── requirements.txt
    ├── CLAUDE.md                  ← this file
    │
    ├── inputs/                    user-provided + cached masters, scoped per plant
    │   ├── ctp/
    │   │   ├── Apr_CTP_PCR_Requirement.xlsx    CTP demand (Initial + Revised iter sheets)
    │   │   ├── daily_moulds_pcr_YYYY-MM-DD.csv Day-1 running moulds
    │   │   └── masters/                         auto-pulled from MySQL on first run
    │   │       ├── cycle_times.xlsx
    │   │       ├── machine_allowable.xlsx
    │   │       ├── gt_inventory.xlsx
    │   │       └── mould_master.xlsx
    │   └── btp/
    │       ├── (BTP demand workbook — TBD)
    │       ├── (BTP day-1 moulds — TBD)
    │       └── masters/                         auto-pulled per --plant btp
    │
    ├── state/<plant>/             auto-managed; never edit by hand
    │   ├── original_plan.csv      frozen Day-1 base demand (kept as the `Original_Demand` reference column / "vs Original" KPI row)
    │   ├── baseline_plan.csv      most-recent committed plan (last applied revision) — the DENOMINATOR for fulfillment KPIs
    │   ├── open_demand.csv        current open balance per SKU (decremented daily)
    │   ├── cumulative_actuals.csv running total of simulated actuals per SKU
    │   ├── running_moulds.csv     current mould state per machine (rolled daily)
    │   ├── forced_changeovers_log.csv cumulative log of wrapper-forced rotations
    │   └── sim_meta.csv           study metadata (start_date, current_day_idx)
    │
    ├── runs/<plant>/2026-MM-DD/   per-day audit dump (one folder per simulated day)
    │   ├── lp_shift_schedule_30day.csv
    │   ├── lp_demand_fulfillment.csv
    │   ├── lp_machine_utilization.csv
    │   ├── today_actuals.csv      Scheduled, factor, Actual side-by-side
    │   ├── open_demand_after.csv
    │   ├── actuals_factors.json   {sku: factor used today}
    │   └── summary.json
    │
    ├── outputs/<plant>/           final artefacts per plant study
    │   ├── final_kpi_report.xlsx  8-sheet KPI workbook
    │   ├── ideal_baseline/        CSVs from the one-shot 30-day LP run
    │   └── per_day_summary.json
    │
    └── V1/                        modular code (plant-agnostic)
        ├── config/settings.py     loads configs/<plant>.yaml; scopes paths
        ├── setups/
        │   ├── master_data.py     DB pull + cache reload of LP master tables
        │   ├── input_loader.py    demand sheets + Day-1 moulds (consumed→remaining)
        │   └── state_initializer.py first-time creation of state/<plant>/ files
        ├── utilities/
        │   ├── lp_adapter.py      wraps JK_LP_Curing_Scheduler_v2.run()
        │   ├── state_io.py        atomic R/W (writes under settings.STATE)
        │   ├── actuals_simulator.py draws ±5%/+2% factor per SKU per day
        │   ├── demand_manager.py  build_demand_for_lp / decrement / apply_revision
        │   ├── moulds_manager.py  decrement life; auto-rotate idle presses
        │   └── archiver.py        per-day audit dump under runs/<plant>/
        ├── routes/
        │   ├── daily_route.py     one full day of the simulation loop
        │   ├── revision_route.py  apply revision before that day's daily run
        │   └── simulation_route.py end-to-end driver: ideal baseline + N-day loop + report
        └── reports/
            ├── kpi_calculator.py  builds simulated counterparts of LP's 5 sheets
            ├── stability_tracker.py schedule-nervousness metric (plan-vs-plan)
            └── kpi_excel_writer.py writes the 8-sheet workbook with banners/colors
```

---

## How to run

**Prereqs once:** `pip3 install -r requirements.txt`. MySQL must be reachable on the first run for that plant (or for `--refresh-masters`); after that everything reads from `inputs/<plant>/masters/`.

```bash
cd /Users/anmolsaini/Documents/freezing_plan/freezing_simulation

# CTP plant (default)
python3 main.py                              # full study, plant=ctp
python3 main.py --plant ctp --reset          # explicit; clear ctp state then run
python3 main.py --plant ctp --smoke-test     # one-day foundation check

# BTP plant (after BTP LP code is dropped + configs/btp.yaml is filled in)
python3 main.py --plant btp --refresh-masters --smoke-test
python3 main.py --plant btp --reset

# Refresh masters for a plant (e.g. mould master changed in DB)
python3 main.py --plant ctp --refresh-masters
```

`main.py` is the **only** entry point. The `--plant` flag selects the config and scopes all state/runs/outputs paths per plant — running `--plant ctp` cannot affect a `--plant btp` study and vice versa.

Master data is fetched on the first run for each plant and reused thereafter; the smoke test takes ~10 sec; a 20-day study takes ~3–5 min on a laptop.

---

## Configuration (`configs/<plant>.yaml`)

| Key | Purpose |
|---|---|
| `start_date` | First simulated day (YYYY-MM-DD) |
| `simulation_days` | How many days the loop runs (CTP study = 30; BTP May study = 31) |
| `planning_days` | LP horizon per daily run. CTP = 30; **BTP = 31** (matches the BTP LP's native `Config.PLANNING_DAYS = 31`). Never go *below* 30 — see decision #6. The wrapper sets `LPConfig.PLANNING_DAYS` from this value at runtime. |
| `shift_start_hour` | 7 (matches LP's `Config.SHIFT_START_HOUR`) |
| `plant` | Plant identifier (`ctp` or `btp`) — must match the file name |
| `demand_file` | Path to demand workbook relative to `freezing_simulation/` |
| `base_demand_sheet` | Sheet name for the Day-1 baseline ("Initial demand") |
| `revision_sheets` | List of `{day, sheet}` entries; revisions apply before that day's daily run |
| `day1_moulds_file` | Path to the Day-1 running-moulds CSV |
| `target_mould_life` | 3000 cycles (cap; used for consumed→remaining conversion) |
| `consolidation_enabled` | `true` (default). When a press's SKU finishes, re-assign the freed press only if some SKU still needs more presses to finish in the time left (tail-consolidation, decision #2). Set `false` to restore the legacy "never idle — force-mount the highest-priority compatible unmet SKU" behaviour. |
| `consolidation_single_press_threshold` | 1200. If a SKU's remaining open demand is below this, one press is deemed enough (skip the min-presses formula). |
| `consolidation_slack` | 0.9. Headroom factor on the per-press capacity in the min-presses formula (`min_presses = ceil(work_min / (cap_per_press · slack))`). Lower ⇒ provision more presses per SKU. |
| `actuals_low_pct` / `actuals_high_pct` | -0.05 / +0.02 — the random factor band per SKU per day |
| `random_seed` | 42 (fixed → reproducible). Set to `null` for fresh randomness each run. |
| `tyre_type` | `pcr` only for now (TBR will be added later) |
| `lp_module_path` | Relative path to the LP folder (sibling repo) |
| `final_report_name` | Output workbook filename inside `outputs/` |

**Adding a new revision** (e.g., when iteration-2 arrives on Day 21):
1. Add a new sheet `Revised iteration 2 demand` to the CTP Excel.
2. Append to `config.yaml`:
   ```yaml
   revision_sheets:
     - day: 11
       sheet: Revised iteration 1 demand
     - day: 21
       sheet: Revised iteration 2 demand
   ```
3. Bump `simulation_days` from 20 → 30.
4. `python3 main.py --reset`.

---

## Input file formats

### CTP demand workbook (`Apr_CTP_PCR_Requirement.xlsx`)

Multiple sheets per file:
- `Initial demand` — Day-1 baseline.
- `Revised iteration 1 demand` — Day-11 revision.
- (Future) `Revised iteration 2 demand` — Day-21 revision.

Columns (all sheets identical):
| Column | Type | Use |
|---|---|---|
| `SKUCode` | str | SAP material code |
| `Base_Requirement` | float | informational only — wrapper uses `Updated_Requirement` |
| `Updated_Requirement` | float | the qty in tyres — read as the demand `Quantity` |
| `Order_Type` | str | informational only |
| `ConsolidatedPriorityScore` | float | the priority — read as `Priority` |

### Day-1 running moulds CSV

Columns: `WCNAME, Current MouldNo, Sapcode, SKU Description, Mould life, Target Life`.

**IMPORTANT — `Mould life` is CONSUMED cycles, not remaining.** The wrapper converts at I/O boundary in [`V1/setups/input_loader.py`](V1/setups/input_loader.py):

```python
df["Mould life"] = (target_life - df["Mould life"].astype(int)).clip(lower=0)
# → now df["Mould life"] == remaining cycles, matching what the LP expects
```

`Current MouldNo` is `LH#RH` format (e.g., `GC01#GC02`). Wrapper splits on `#`, takes both halves as the press's mould pair, and uses `min(LH_life, RH_life)` for `MouldLife_remaining` (matches the LP's DB ETL logic).

---

## Output: KPI report (`outputs/final_kpi_report.xlsx`)

Eight sheets — first five mirror the LP's existing output structure for apples-to-apples comparison; last three are new wrapper-specific views.

| # | Sheet | Source | What it shows |
|---|---|---|---|
| 1 | Demand Fulfillment | simulated cumulative | per-SKU `Demand` (latest revised) + `Original_Demand` (Day-1 ask) vs `Actual_Units` (post-factor cumulative) + Status (vs latest) |
| 2 | Machine Schedule | simulated cumulative | aggregated `Actual_Cycles`, `Actual_Units`, `Mins_Used` per (machine, SKU) |
| 3 | Shift Schedule | concatenated daily Day-1 | every block: `Scheduled_Qty`, `Factor_Pct`, `Actual_Qty` (verifies the conversion row-by-row) |
| 4 | Machine Utilization | simulated cumulative | per-press `Used_Mins`, `Idle_Mins`, `Utilization_Pct`, `Actual_Total_Units` |
| 5 | Mould Tracker | end-of-study state | final `running_moulds` snapshot |
| 6 | Ideal vs Simulated | comparison | side-by-side KPIs: ideal single-shot LP vs simulated daily-rerun (fulfillment shown **vs latest revised** [primary] *and* vs Day-1 original) |
| 7 | Per-Day History | per-day | `Scheduled_Units`, `Actual_Units`, `Open_Balance_End`, `Forced_Rotations` |
| 8 | Schedule Stability | plan-vs-plan | how much today's LP plan for a future date shifted from yesterday's plan for the same date |
| 9 | Changeover Breakdown | per-day | LP-scheduled CO vs wrapper-forced CO vs total |
| 10 | Forced Rotations Log | per event | every individual wrapper-induced press rotation |

### Naming convention — IMPORTANT

Any column representing **post-factor** simulated production starts with `Actual_`:
- `Actual_Qty` (Shift Schedule rows)
- `Actual_Units` (cumulative across study)
- `Actual_Cycles` (= `Actual_Units / 2`)
- `Actual_Total_Units` (per-machine across study)

Columns NOT factor-adjusted:
- `Used_Mins` — LP-scheduled minutes the press was running. The factor applies only to qty, **not** to running time. The press ran for the LP's planned duration regardless of the factor.
- `Scheduled_Units`, `Scheduled_Qty` — pre-factor LP plan.

Demand columns on the *Demand Fulfillment* sheet:
- `Demand` — the **latest revised committed quantity** (last applied revision); this is the fulfillment denominator and what `Gap` / `Fulfillment_Pct` / `Status` are computed against.
- `Original_Demand` — the frozen **Day-1** ask for that SKU (0 for SKUs that only appeared in a revision); reference only.

### What "actual" means in this simulation

There is **no real plant data feed**. The simulator INVENTS actuals:

```
actual_qty = scheduled_qty × (1 + Uniform(-5%, +2%))
            ↑                              ↑
      from LP plan              one independent random draw
                              per SKU per day, applied to all
                              machines producing that SKU
```

The formula's output IS what we treat as "produced". When a real shop-floor data feed becomes available, replace `V1/utilities/actuals_simulator.py` and everything else keeps working — that's why it's a separate module.

---

## Key design decisions (and the reasons)

### 1. Mould life conversion lives in the wrapper, not the LP
The daily moulds CSV stores **consumed** cycles. The LP's `MouldTracker` expects **remaining**. Wrapper does the conversion in `input_loader.load_day1_moulds`. The user also added the same conversion inside the LP's DB ETL for direct DB runs — both paths are now consistent.

### 2. Tail-consolidation when a SKU finishes on a press
[`V1/utilities/moulds_manager.roll()`](V1/utilities/moulds_manager.py) handles a freed-up press with a **tail-consolidation policy** (controlled by `consolidation_enabled`, default `true`):

1. Presses whose running SKU still has open demand > 0 → kept unchanged, no rotation (as before; mould life decremented from today's actuals).
2. Presses whose running SKU just finished (open balance hit 0) **plus any press that produced nothing today** form the pool of "available" presses for re-assignment.
3. For every SKU with remaining open demand, compute the **minimum** number of presses it needs to finish that demand within the remaining study horizon:
   - `work_min = open_demand / 2 · CycleTime_min` (2 tyres per cycle; cycle time from the cycle-times master)
   - `cap_per_press = (simulation_days − day_idx) · 24 · 60` (press-minutes left in the study)
   - `min_presses = max(1, ceil(work_min / (cap_per_press · consolidation_slack)))`, then capped at the count of compatible presses (`df_allow`)
   - Shortcut: if `open_demand < consolidation_single_press_threshold` → `min_presses = 1`.
4. `deficit(SKU) = max(0, min_presses − #still-running presses currently mounting that SKU)`.
5. Walking SKUs in priority order (highest `ConsolidatedPriorityScore` first), assign up to `deficit` of the available presses that are compatible with the SKU (per `df_allow`). When choosing which available press, prefer one whose currently-mounted mould pair is already valid for the new SKU (fewest physical mould swaps; that press keeps its mould pair and remaining life), falling back to any compatible available press (fresh pair from `mould_master`, life reset to 3000). Each assignment is one forced rotation, logged exactly as before (`Machine/From_SKU/To_SKU` → `forced_changeovers_log`).
6. Available presses left unassigned after step 5 are **dropped** (left idle). We do NOT force a changeover just to avoid idleness, and we never proactively pull a still-running SKU off a press to consolidate — only naturally-freed presses are re-assigned.

Fulfillment is not sacrificed: every SKU with open demand still gets at least enough presses to finish it in the time left (subject to compatible-press availability and priority contention).

**To restore the old behaviour** (drop nothing; always force-mount the highest-priority compatible unmet SKU on a freed press), set `consolidation_enabled: false` in the plant config. The three knobs `consolidation_enabled` / `consolidation_single_press_threshold` / `consolidation_slack` live in `configs/<plant>.yaml` and reach `roll()` via `cfg` in `daily_route.run_one_day`.

*Why this changed:* the original "never idle while a compatible unmet SKU exists" rule produced a huge tail of wrapper-forced changeovers in the demand-drained last week of a study — the leftover demand of a few SKUs got scattered across dozens of presses (e.g. one BTP SKU with 310 tyres of demand ran on 25 presses; Day 30 had ≈90 forced rotations). The user authorised relaxing this decision to a consolidation policy that prevents unnecessary changeovers while still guaranteeing each SKU enough presses to be fully met.

### 3. `CHANGEOVER_PENALTY_WEIGHT` stays at 0.01 — DO NOT TUNE GLOBALLY
The user explicitly decided against lowering the LP's changeover penalty as a way to force higher utilization. The wrapper handles the idle-press question itself in `moulds_manager.roll()` (tail-consolidation, decision #2) without distorting the LP's planning behaviour for currently-running ones. If you find yourself tempted to change this constant in [`jk_curing_lp_PCR.py:96`](../jk-btp-lp-scheduler-main/btp/Curing/V1/jk_curing_lp_PCR.py#L96), don't — discuss with the user first.

### 4. Schedule Stability compares plan-vs-plan, not actuals
Future-day actuals don't exist (only Day-1 of each rerun is "real"). The only thing we can compare across consecutive daily reruns for a future target date is **the LP's plan** for that date today vs. yesterday. So the Schedule Stability sheet uses LP-planned `Qty`, by design.

### 5. Demand-fulfillment denominator is the LATEST REVISED plan (Day-1 original kept as reference)
The fulfillment % headline compares cumulative simulated actuals against the **most recent committed demand** — i.e. the last applied revision (`state/baseline_plan.csv`; for a study with Day-11 + Day-21 revisions this is the 2nd iterative demand, and it equals the base demand when no revision ran). The frozen Day-1 base plan (`state/original_plan.csv`) is still carried as the `Original_Demand` reference column on the *Demand Fulfillment* sheet and as a "Fulfillment % vs Original Day-1 Plan" row on the *Ideal vs Simulated* sheet, so the apples-to-apples comparison with the ideal one-shot LP (which only ever planned against the Day-1 demand) is preserved. SKU status (FULLY MET / PARTIAL / UNMET) is computed against the latest revised demand for both columns; for the ideal column that means re-statusing its Day-1 plan against the latest ask (SKUs the Day-1 plan never produced — e.g. revision-added SKUs — count as UNMET).

*Why this changed:* the original spec used the Day-1 plan as the **sole** denominator; the planner asked for the latest revision instead — that is the real commitment, and revision-added SKUs were otherwise invisible in the denominator. Implemented in `kpi_calculator._demand_basis()` (reads `baseline_plan` for "latest", `original_plan` for the reference column). A SKU listed more than once in a revision sheet is collapsed to its largest stated quantity in the KPI layer; note the underlying `open_demand` / `demand_manager.apply_revision()` path does **not** yet de-dup such rows (a SKU duplicated in a revision sheet gets two `open_demand` rows that are both decremented by the same actuals) — known data-quality edge, fix later.

### 6. The LP planning horizon is always 30 days, never less
Cutting the LP's horizon to "1 day at a time" would defeat its global optimisation:
- Continuity logic locks running moulds for 30 days of demand satisfaction; a 1-day LP wouldn't see this.
- Changeover penalty discourages spreading SKUs across the full horizon; a 1-day LP would think changeovers are free.
- Mould-clean scheduling (every 12,000 units) needs ≥10 days of visibility.

If you need to speed up the simulation, optimise within the 30-day frame (e.g., warm-start) — don't shrink it.

### 7. Random seed is fixed for reproducibility
`random_seed: 42` in `config.yaml`. Any A/B comparison (e.g., "what if I change the priority formula?") must use the same seed so differences in KPIs reflect the change, not random noise. Set to `null` only when intentionally measuring noise sensitivity.

### 8. State files use atomic write (write-temp-then-rename)
`state_io.write_state` writes to a temp file in `state/` then `os.replace`s it onto the target. A crashed run never leaves a half-written state CSV. Re-running with `--reset` clears state for a clean study; otherwise the simulation resumes from where it stopped.

---

## Things to know / caveats

- **Currently 20 simulation days, not 30.** Only the iteration-1 revision sheet exists. When CTP delivers iteration-2, follow the "Adding a new revision" steps and bump `simulation_days` to 30.
- **PCR only.** TBR exists in `jk_curing_lp_TBR.py` but is not wired into this wrapper. Expanding to TBR will require a `tyre_type` parameter throughout the data path.
- **No holiday calendar yet.** April 2026 has 30 working days, no holidays — so this isn't a concern. When a future month has holidays, see the deferred holiday-handling discussion (reduce `planning_days` or pass holiday list to LP).
- **GT inventory is not used by the LP.** Loaded and displayed for transparency only. Do not assume it reduces demand anywhere.
- **Plan-as-truth.** Without a real shop-floor feed, the simulator is the only source of "actuals". Be careful interpreting fulfillment % as a real-world prediction — it's a simulation under the assumed variance.
- **Forced changeovers don't subtract 360 min from next-day capacity** in the current model — they're counted in KPIs but the LP's continuity time is not reduced. This is a known small modelling simplification; revisit if results are sensitive to it.
- **Tail-consolidation drops idle presses from `running_moulds`** (decision #2). A press that produced nothing today and isn't needed by any under-provisioned SKU is removed from the rolled `running_moulds` rather than keeping its (now-irrelevant) mount. This is by design — the LP re-decides such a press's mount next day anyway. With `consolidation_enabled: false` the legacy behaviour (keep idle presses' mounts, force-mount on freed presses) returns.
- **`min_presses` depends on `simulation_days`** — the consolidation formula uses the days left until the study ends, so the policy naturally tightens as the study winds down. On the final day's roll (`day_idx == simulation_days`) no re-assignment happens (no tomorrow to plan).

---

## Don't do this

- **Don't modify the LP** (`jk_curing_lp_PCR.py`). It's a separate product. The wrapper interfaces with it via `lp_adapter.run_lp()` only. If the LP genuinely needs a fix, raise it with the LP owner.
- **Don't lower `CHANGEOVER_PENALTY_WEIGHT`** without discussion (see decision #3).
- **Don't write to `state/` files outside of `state_io`.** Always use `state_io.read_state` / `state_io.write_state` to preserve atomicity.
- **Don't change the LP's `PLANNING_DAYS` to a smaller number** to "speed it up" (see decision #6).
- **Don't double-convert mould life** — the wrapper already converts CSV consumed → remaining in `input_loader`. Don't add a second `3000 - life` anywhere.
- **Don't include CHANGEOVER or MOULD_CLEAN rows in production sums** — filter by `SKUCode not in ['CHANGEOVER', 'MOULD_CLEAN']`. This is more robust than filtering by Remarks (which has multiple variants).
- **Don't put the original CTP file in two places** — there's one source of truth at `inputs/Apr_CTP_PCR_Requirement.xlsx`. The same file is in `../jk-btp-lp-scheduler-main/btp/Curing/V1/` for the LP's standalone use, but our wrapper points at the local copy via config.

---

## Roadmap (deferred items)

| Item | Trigger |
|---|---|
| Add iteration-2 revision sheet & extend study to 30 days | When CTP delivers it |
| Holiday calendar in `config.yaml` + LP holiday-aware capacity | When a study month has holidays |
| TBR support (multi-tyre-type runs) | When user expands scope beyond PCR |
| Replace `actuals_simulator` with real shop-floor data feed | When the data feed becomes available |
| Subtract 360-min forced-CO time from next-day machine capacity | If KPI accuracy demands it |
| Manager-friendly second stability metric (vs Day-1 baseline) | If the consecutive-day metric proves too noisy |
| Sensitivity sweeps over actuals factor band | If the user wants to stress-test variance assumptions |

---

## Quick smoke test (sanity check after any change)

```bash
python3 main.py --smoke-test
```

Should print `[Smoke OK] Foundation is wired correctly.` and a Day-1 LP summary in <30 seconds. If it fails, check the trace and don't proceed to a full run.
