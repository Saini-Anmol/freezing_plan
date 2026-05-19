---
name: codebase-quirks
description: Practical gotchas in freezing_simulation — smoke-test coverage, KPI report layout, config plumbing, master DataFrame schemas
metadata:
  type: project
---

Working notes for the freezing_simulation wrapper (cwd `/Users/anmolsaini/Documents/freezing_plan/freezing_simulation`).

**Smoke test scope.** `python3 main.py --plant <plant> --smoke-test` only loads masters + inputs + one LP call (`main.smoke_test`). It does NOT exercise the daily loop, so it does NOT run `moulds_manager.roll()` or `daily_route.run_one_day()`. A green smoke test after editing those modules only proves imports/signatures are sound. To actually exercise roll() / consolidation you need `--reset` (full study) — a 31-day BTP study takes a few minutes.

**Plant config is just a dict.** `settings.load_config()` does `yaml.safe_load` then resolves a few paths and the revision map; every other YAML key passes straight through into `cfg`. So adding a new knob to `configs/<plant>.yaml` is enough — no `settings.py` change needed. Read it in code via `cfg.get("key", default)`.
**Why:** keeps new config knobs cheap. **How to apply:** when asked to "add a config knob loaded via settings.py", just add the YAML key and `cfg.get()` it; mention that settings.py needs no change.

**Threading masters/day_idx/cfg into roll().** `daily_route.run_one_day(day_idx, day_date, cfg, masters, rng)` already has `masters["cycles"]` (cols `SKUCode`, `CycleTime_min`), `masters["allowable"]` (cols `SKUCode`, `Machines` — Machines is a Python list), `masters["mould_master"]` (cols incl `MouldNo`, `Matl.Code`), `day_idx`, and `cfg["simulation_days"]`. Pass these to `moulds_manager.roll()` from there.

**KPI report layout (`outputs/<plant>/final_kpi_report.xlsx`).** Every sheet has a 1–2 row banner before the real header. `Changeover Breakdown`: banner row 0 has the totals string `LP-Scheduled: N | Wrapper-Forced (idle-machine pickup): M | Total: T`; real header at row 1 (cols `Day_Idx, Date, LP_Scheduled_CO, Wrapper_Forced_CO, Total_CO`). `Machine Utilization`: header at row 2, cols `Machine, Available_Mins, Used_Mins, Idle_Mins, Utilization_Pct, Actual_Total_Units`, 170 data rows. `Ideal vs Simulated`: header at row 2, `Metric / Ideal_Single_Shot / Simulated_Daily_Rerun / Delta`. `Demand Fulfillment`: header at row 2, cols incl `SKUCode, Priority, Demand, Original_Demand, Actual_Units, Gap, Fulfillment_Pct, Status`. To parse: `pd.read_excel(xl, sheet, header=<n>)` then drop banner-ish rows.

**Bash sandbox is fussy about `python3 -c` with multi-line strings** containing certain characters — it sometimes denies. Workaround: write a tiny `_tmp.py` script with the Write tool, run `python3 _tmp.py`, then delete it. Don't leave temp scripts behind.

**Validation chain after a study-affecting change:** `--smoke-test` → `--reset` (full study, wipes `outputs/<plant>/`) → `python3 gen_ideal_report.py --plant <plant>` (regenerates the ideal report that `--reset` wiped) → read `outputs/<plant>/final_kpi_report.xlsx`.
