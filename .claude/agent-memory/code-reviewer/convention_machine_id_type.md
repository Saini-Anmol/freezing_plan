---
name: Machine ID type convention (str vs int)
description: The wrapper's authoritative type for Machine is string; the LP emits mixed types in shift_schedule. Reviews should flag any cast-to-int at wrapper boundaries.
type: project
---

The wrapper consistently uses **string-typed Machine IDs** in its state and comparisons:
- `V1/setups/input_loader.py` end of `load_day1_moulds` casts Machine via `astype(str)` before writing `running_moulds.csv`.
- `V1/utilities/moulds_manager.py` `roll()` does `df_shift_today["Machine"] = df_shift_today["Machine"].astype(str)` and uses `str(mrow["Machine"])` for comparisons.
- The LP's continuity path (`jk_curing_lp_PCR.py:1180`, `btp_curing.py:1013`) uses `mach = str(row["Machine"])` to match this.

The LP's allocator path emits Machine as **int** (from `df_allow["Machines"]` lists, which `master_data.load` parses to lists of ints via `ast.literal_eval`). After `pd.concat` of continuity rows + allocator rows, `shift_schedule["Machine"]` is `object` dtype with mixed `str` / `int` values.

**Why:** The 30-day CTP study reported avg utilization 68.68% vs ideal 94.38% — a 25.7-pt gap caused by `kpi_calculator.build_simulated_machine_utilization` doing `groupby("Machine")` on the mixed-type column, splitting each physical press into two groups (`'3609'` vs `3609`). The LP's ideal `_build_util` sidesteps the bug at line 1363 with `prod['Machine'] = prod['Machine'].astype('int64')`. The wrapper does not.

**How to apply:**
- When reviewing fixes for Machine-type issues, prefer normalizing to **string**, not int, at wrapper boundaries — matches running_moulds.csv, moulds_manager, input_loader, and the LP's own continuity convention.
- Casting Machine to int via `pd.to_numeric` is unsafe across plants — BTP's `Machine` column is built from `WCNAME.str.replace(r"(LH|RH)$", "")` and may include non-numeric IDs that would silently coalesce to `Machine=0` under `errors="coerce"`.
- The narrowest correct boundary is `daily_route.run_one_day` immediately after `lp_adapter.run_lp(...)` returns: normalizing on `lp_results["shift_schedule"]["Machine"]` covers `today_prod`, `today_shift` for moulds_manager, `count_simulated_changeovers_and_cleans`, `build_changeover_breakdown`, and `stability_tracker` in one place.
- A meaningful regression guard for this bug is `assert sim_util["Machine"].dtype != object` or `len(sim_util) <= physical_machine_count`. `nunique == len` is tautologically true for any groupby output and cannot detect the bug.
