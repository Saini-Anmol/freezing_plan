"""One simulated day:
   1. Read state (open_demand, running_moulds)
   2. Run LP for [today, today+30 days)
   3. Extract today's production from the LP's shift schedule
   4. Apply ±5%/+2% per-SKU random factor to get simulated actuals
   5. Decrement open_demand and cumulative_actuals
   6. Roll running_moulds for tomorrow
   7. Archive the day's artefacts under runs/YYYY-MM-DD/
"""
from __future__ import annotations

from datetime import datetime, date, timedelta

import numpy as np
import pandas as pd

from V1.utilities import (
    actuals_simulator, archiver, demand_manager, lp_adapter, moulds_manager, state_io,
)


def _extract_today_production(df_shift: pd.DataFrame, today: date) -> pd.DataFrame:
    """Filter shift schedule to today's PRODUCTION rows only (skip CO/CLEAN)."""
    if df_shift is None or df_shift.empty:
        return pd.DataFrame(columns=["Date", "Machine", "SKUCode", "Qty"])
    df = df_shift.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    today_rows = df[df["Date"] == today]
    prod = today_rows[~today_rows["SKUCode"].isin(["CHANGEOVER", "MOULD_CLEAN"])].copy()
    return prod[["Date", "Machine", "SKUCode", "StartTime", "EndTime", "Qty"]].reset_index(drop=True)


def run_one_day(
    day_idx: int,
    day_date: date,
    cfg: dict,
    masters: dict,
    rng: np.random.Generator,
) -> dict:
    """Execute one simulated day. Returns a small summary dict for the driver."""
    print(f"\n{'─'*70}\n  DAY {day_idx:2d}  |  {day_date.isoformat()}\n{'─'*70}")

    df_demand = demand_manager.build_demand_for_lp()
    if df_demand.empty:
        print("  [Daily] No open demand left — skipping LP, marking day idle.")
        return {"day_idx": day_idx, "day_date": day_date,
                "today_scheduled": 0, "today_actual": 0, "open_after": 0}

    df_running = moulds_manager.load_running_moulds_for_lp()
    plan_start = datetime.combine(
        day_date, datetime.min.time().replace(hour=cfg["shift_start_hour"])
    )

    lp_results = lp_adapter.run_lp(
        df_demand=df_demand,
        df_cycles=masters["cycles"],
        df_allow=masters["allowable"],
        df_gt=masters["gt"],
        df_mould_master=masters["mould_master"],
        df_running=df_running,
        plan_start=plan_start,
        planning_days=cfg["planning_days"],
        lp_module_path=cfg["lp_module_path"],
    )

    df_shift = lp_results["shift_schedule"]
    today_prod = _extract_today_production(df_shift, day_date)

    if today_prod.empty:
        print("  [Daily] LP produced no rows for today — moulds rolled, no decrement.")
        actuals = today_prod.assign(Actual_Qty=0)
        factors: dict[str, float] = {}
    else:
        scheduled_by_sku = today_prod.groupby("SKUCode", as_index=False)["Qty"].sum()
        skus = scheduled_by_sku["SKUCode"].tolist()
        factors = actuals_simulator.draw_factors(
            skus, cfg["actuals_low_pct"], cfg["actuals_high_pct"], rng,
        )
        actuals = actuals_simulator.apply_to_scheduled(today_prod, factors)
        sku_actuals = actuals.groupby("SKUCode")["Actual_Qty"].sum().astype(int).to_dict()
        demand_manager.decrement_open_demand(sku_actuals)

    open_after = demand_manager.build_demand_for_lp()
    today_shift = df_shift[pd.to_datetime(df_shift["Date"]).dt.date == day_date] \
        if not df_shift.empty else pd.DataFrame()
    _, forced_rotations = moulds_manager.roll(
        df_shift_today=today_shift,
        open_demand_after=open_after if not open_after.empty
            else pd.DataFrame(columns=["SKUCode", "Quantity", "Priority"]),
        actuals_factors=factors,
        df_mould_master=masters["mould_master"],
        df_allow=masters["allowable"],
        df_cycles=masters["cycles"],
        day_idx=day_idx,
        simulation_days=cfg["simulation_days"],
        target_life=cfg["target_mould_life"],
        consolidation_enabled=cfg.get("consolidation_enabled", True),
        consolidation_single_press_threshold=cfg.get(
            "consolidation_single_press_threshold", 1200.0),
        consolidation_slack=cfg.get("consolidation_slack", 0.9),
    )
    if forced_rotations:
        for r in forced_rotations:
            r["Date"] = day_date.isoformat()
            r["Day_Idx"] = day_idx
        new_log = pd.DataFrame(forced_rotations,
                               columns=["Day_Idx", "Date", "Machine", "From_SKU", "To_SKU"])
        if state_io.state_exists("forced_changeovers_log"):
            existing = state_io.read_state("forced_changeovers_log")
            new_log = pd.concat([existing, new_log], ignore_index=True)
        state_io.write_state("forced_changeovers_log", new_log)

    archiver.archive_day(day_date, day_idx, lp_results, actuals, factors,
                         open_after if not open_after.empty
                         else pd.DataFrame(columns=["SKUCode", "Quantity"]))

    today_sched_units = int(today_prod["Qty"].sum())
    today_actual_units = int(actuals["Actual_Qty"].sum())
    open_remaining = int(open_after["Quantity"].sum()) if not open_after.empty else 0
    n_forced = len(forced_rotations)
    print(f"  [Daily] Scheduled={today_sched_units:,}  Actual={today_actual_units:,}  "
          f"Open balance after={open_remaining:,}  Forced rotations={n_forced}")

    return {
        "day_idx": day_idx,
        "day_date": day_date,
        "today_scheduled": today_sched_units,
        "today_actual": today_actual_units,
        "open_after": open_remaining,
        "forced_rotations": n_forced,
        "lp_results": lp_results,
        "today_prod": today_prod,
        "today_actuals": actuals,
    }
