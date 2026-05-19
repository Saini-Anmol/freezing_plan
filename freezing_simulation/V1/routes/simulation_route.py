"""End-to-end driver: run the simulation from Day 1 to Day N.

Flow:
  - Initialise state from base demand + day-1 moulds (if not already initialised)
  - Cache the IDEAL 30-day single-shot LP output (used for Ideal-vs-Simulated KPI)
  - Loop day_idx = 1..simulation_days:
      * If revision is configured for this day, apply it before the daily run
      * Run daily_route for the day
      * Track per-day summary for stability + KPI reporting
  - At end, hand off the per-day history to the report builder
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from V1.config import settings
from V1.routes import daily_route, revision_route
from V1.setups import input_loader, state_initializer
from V1.utilities import actuals_simulator, lp_adapter, moulds_manager
from datetime import datetime


def _save_ideal_baseline(cfg: dict, masters: dict) -> dict:
    """Run the LP exactly once on Day 1's pristine state to capture the
    IDEAL 30-day single-shot plan. This is the apples-to-apples reference
    against which the simulated 30-day rerun results are compared.
    """
    print("\n[Ideal] Capturing single-shot 30-day baseline (no actuals, no rerun)")
    df_demand = input_loader.load_demand_sheet(
        cfg["demand_file"], cfg["base_demand_sheet"]
    )
    df_running = input_loader.load_day1_moulds(
        cfg["day1_moulds_file"], cfg["target_mould_life"]
    )
    plan_start = datetime.combine(
        cfg["start_date"],
        datetime.min.time().replace(hour=cfg["shift_start_hour"]),
    )
    ideal = lp_adapter.run_lp(
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

    ideal_dir = settings.OUTPUTS / "ideal_baseline"
    ideal_dir.mkdir(parents=True, exist_ok=True)
    if not ideal["shift_schedule"].empty:
        ideal["shift_schedule"].to_csv(ideal_dir / "shift_schedule.csv", index=False)
    if not ideal["demand_fulfillment"].empty:
        ideal["demand_fulfillment"].to_csv(ideal_dir / "demand_fulfillment.csv", index=False)
    if not ideal["machine_utilization"].empty:
        ideal["machine_utilization"].to_csv(ideal_dir / "machine_utilization.csv", index=False)
    if not ideal["machine_schedule"].empty:
        ideal["machine_schedule"].to_csv(ideal_dir / "machine_schedule.csv", index=False)
    if not ideal["mould_tracker"].empty:
        ideal["mould_tracker"].to_csv(ideal_dir / "mould_tracker.csv", index=False)

    return ideal


def run(cfg: dict, masters: dict) -> dict:
    """Run the full study end-to-end. Returns history dict for reporters."""
    if not state_initializer.state_already_initialised():
        print("\n[Init] No prior state found — initialising from inputs")
        df_base = input_loader.load_demand_sheet(
            cfg["demand_file"], cfg["base_demand_sheet"]
        )
        df_day1_moulds = input_loader.load_day1_moulds(
            cfg["day1_moulds_file"], cfg["target_mould_life"]
        )
        state_initializer.initialise(df_base, df_day1_moulds, cfg["start_date"])
    else:
        print("\n[Init] Prior state found — resuming (use --reset to start fresh)")

    ideal = _save_ideal_baseline(cfg, masters)

    rng = actuals_simulator.make_rng(cfg["random_seed"])
    revisions = cfg["revision_by_day"]

    per_day = []
    for day_idx in range(1, cfg["simulation_days"] + 1):
        day_date = cfg["start_date"] + timedelta(days=day_idx - 1)

        if day_idx in revisions:
            revision_route.apply(day_idx, revisions[day_idx], cfg)

        summary = daily_route.run_one_day(day_idx, day_date, cfg, masters, rng)
        per_day.append(summary)

    print(f"\n{'═'*70}\n  SIMULATION COMPLETE — {cfg['simulation_days']} days\n{'═'*70}")

    history = {
        "ideal": ideal,
        "per_day": per_day,
        "cfg": cfg,
        "masters": masters,        # so reports can look up authoritative
                                    # Eligible_Machines / CycleTime_min for
                                    # SKUs the ideal one-shot never saw
                                    # (e.g. SKUs added by a later revision).
    }

    summary_path = settings.OUTPUTS / "per_day_summary.json"
    with open(summary_path, "w") as f:
        json.dump([{
            "day_idx": p["day_idx"],
            "day_date": p["day_date"].isoformat(),
            "today_scheduled": p["today_scheduled"],
            "today_actual": p["today_actual"],
            "open_after": p["open_after"],
            "forced_rotations": p.get("forced_rotations", 0),
        } for p in per_day], f, indent=2)
    print(f"  [Driver] Per-day summary -> {summary_path}")

    return history
