"""Freezing Plan Simulation — single entry point.

Usage:
  python3 main.py                       # full study for default plant (ctp)
  python3 main.py --plant btp           # run for BTP plant
  python3 main.py --refresh-masters     # force re-pull master data from DB
  python3 main.py --reset               # clear state/, runs/, outputs/ for that plant
  python3 main.py --smoke-test          # foundation check: load inputs, run LP once

Plant-specific config lives in configs/<plant>.yaml. State, runs, outputs and
masters are all scoped per plant (state/<plant>/, runs/<plant>/, etc.) so two
plants can be studied independently without collision.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime

from V1.config import settings
from V1.config.settings import ensure_dirs, load_config
from V1.setups import master_data, input_loader
from V1.utilities import lp_adapter
from V1.routes import simulation_route
from V1.reports import kpi_excel_writer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plant", default="ctp", choices=["ctp", "btp"],
                   help="Which plant to run (default: ctp). Loads configs/<plant>.yaml.")
    p.add_argument("--refresh-masters", action="store_true",
                   help="Force re-pull of master data from MySQL")
    p.add_argument("--reset", action="store_true",
                   help="Clear state/<plant>/, runs/<plant>/, outputs/<plant>/ before running")
    p.add_argument("--smoke-test", action="store_true",
                   help="Foundation check: load all inputs and run the LP once")
    return p.parse_args()


def reset_workspace() -> None:
    for d in (settings.STATE, settings.RUNS, settings.OUTPUTS):
        if d.exists():
            shutil.rmtree(d)
    ensure_dirs()
    print(f"  [Reset] Cleared state/, runs/, outputs/ for plant '{settings.STATE.name}'")


def smoke_test(cfg: dict) -> None:
    """Wires foundation end-to-end: masters + inputs + a single LP call."""
    print("\n[Smoke 1/4] Loading master data from cache")
    masters = master_data.load()
    print(f"  cycles={len(masters['cycles'])}  "
          f"allowable={len(masters['allowable'])}  "
          f"gt={len(masters['gt'])}  "
          f"mould_master={len(masters['mould_master'])}")

    print("\n[Smoke 2/4] Loading Day-1 demand and running moulds")
    df_demand = input_loader.load_demand_sheet(
        cfg["demand_file"], cfg["base_demand_sheet"]
    )
    df_running = input_loader.load_day1_moulds(
        cfg["day1_moulds_file"], cfg["target_mould_life"]
    )
    print(f"  Demand SKUs: {len(df_demand)}  |  "
          f"Total qty: {df_demand['Quantity'].sum():,}")
    print(f"  Running moulds: {len(df_running)} machines")

    print("\n[Smoke 3/4] Running LP for Day 1")
    plan_start = datetime.combine(
        cfg["start_date"],
        datetime.min.time().replace(hour=cfg["shift_start_hour"]),
    )
    results = lp_adapter.run_lp(
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

    print("\n[Smoke 4/4] LP results summary")
    df_sum = results["demand_fulfillment"]
    df_shift = results["shift_schedule"]
    print(f"  Demand fulfillment rows: {len(df_sum)}")
    print(f"  Shift schedule rows:     {len(df_shift)}")
    print(f"  Total planned units:     "
          f"{int(df_sum['Planned_Units'].sum()):,}")
    print(f"  Total demand:            "
          f"{int(df_sum['Demand'].sum()):,}")
    if not df_shift.empty:
        co_n = int((df_shift['SKUCode'] == 'CHANGEOVER').sum())
        cl_n = int((df_shift['SKUCode'] == 'MOULD_CLEAN').sum())
        print(f"  Changeovers:             {co_n}")
        print(f"  Mould cleans:            {cl_n}")

    print("\n[Smoke OK] Foundation is wired correctly.")


def run_full_simulation(cfg: dict) -> None:
    masters = master_data.load()
    history = simulation_route.run(cfg, masters)
    kpi_excel_writer.write(history)
    print(f"\n[Done] Final report ready in outputs/{cfg['plant']}/")


def main() -> int:
    args = parse_args()

    print("=" * 70)
    print(f"  Freezing Plan Simulation  —  plant: {args.plant.upper()}")
    print("=" * 70)

    cfg = load_config(plant=args.plant)
    ensure_dirs()

    if args.reset:
        reset_workspace()

    print(f"  Study window     : {cfg['start_date']} + {cfg['simulation_days']} days")
    print(f"  Planning horizon : {cfg['planning_days']} days/run")
    print(f"  Demand file      : {cfg['demand_file'].name}")
    print(f"  Day-1 moulds     : {cfg['day1_moulds_file'].name}")
    print(f"  Random seed      : {cfg['random_seed']}")
    print(f"  Revisions        : "
          f"{', '.join(f'day {d}={s}' for d, s in cfg['revision_by_day'].items()) or 'none'}")

    print("\n[Setup] Master data")
    master_data.refresh(cfg, force=args.refresh_masters)

    if args.smoke_test:
        smoke_test(cfg)
        return 0

    run_full_simulation(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
