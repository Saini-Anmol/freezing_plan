"""Generate the LP's native 5-sheet *ideal one-shot* curing-schedule report.

Runs the plant LP exactly once over the configured horizon (`planning_days`)
on the Day-1 base demand + Day-1 running moulds — i.e. the ideal single-shot
plan: no daily rerun, no actuals — and writes the LP's own fully-formatted
Excel workbook with all five sheets:
  Demand Fulfillment / Machine Schedule / Shift Schedule /
  Machine Utilization / Mould Tracker
(the same workbook the LP produces when run standalone).

Usage:
  cd /Users/anmolsaini/Documents/freezing_plan/freezing_simulation
  python3 gen_ideal_report.py --plant btp                      # uses cached masters
  python3 gen_ideal_report.py --plant btp --refresh-masters    # re-pull the 4 masters from MySQL first
  python3 gen_ideal_report.py --plant ctp -o my_report.xlsx

Output (default): outputs/<plant>/ideal_curing_schedule_<horizon>days.xlsx
Side effect: outputs/<plant>/ideal_baseline/*.csv are refreshed as well.
"""
from __future__ import annotations

import argparse
import sys

from V1.config import settings
from V1.config.settings import add_lp_to_path, ensure_dirs, load_config
from V1.setups import master_data
from V1.routes import simulation_route


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--plant", default="btp", choices=["ctp", "btp"],
                   help="Which plant (loads configs/<plant>.yaml). Default: btp.")
    p.add_argument("--refresh-masters", action="store_true",
                   help="Re-pull the 4 master tables from MySQL before running.")
    p.add_argument("-o", "--output", default=None,
                   help="Output .xlsx path (default: outputs/<plant>/ideal_curing_schedule_<N>days.xlsx).")
    args = p.parse_args()

    print("=" * 70)
    print(f"  Ideal one-shot curing schedule report  —  plant: {args.plant.upper()}")
    print("=" * 70)

    cfg = load_config(plant=args.plant)
    ensure_dirs()
    master_data.refresh(cfg, force=args.refresh_masters)
    masters = master_data.load()

    print(f"\n[Ideal report] Running the {args.plant.upper()} LP once over "
          f"{cfg['planning_days']} days from {cfg['start_date']} "
          f"(base demand sheet: '{cfg['base_demand_sheet']}', moulds: {cfg['day1_moulds_file'].name})")
    ideal = simulation_route._save_ideal_baseline(cfg, masters)   # runs the LP; also writes ideal_baseline/*.csv

    add_lp_to_path(cfg["lp_module_path"])
    from jk_curing_lp_PCR import ExcelExporter

    out = args.output or str(
        settings.OUTPUTS / f"ideal_curing_schedule_{cfg['planning_days']}days.xlsx"
    )
    ExcelExporter(out).export(ideal)

    print(f"\n[Ideal report] Wrote: {out}")
    print(f"  Demand Fulfillment : {len(ideal['demand_fulfillment'])} SKUs")
    print(f"  Machine Schedule   : {len(ideal['machine_schedule'])} rows")
    print(f"  Shift Schedule     : {len(ideal['shift_schedule'])} rows")
    print(f"  Machine Utilization: {len(ideal['machine_utilization'])} presses")
    print(f"  Mould Tracker      : {len(ideal['mould_tracker'])} rows")
    print(f"  (CSVs also refreshed in {settings.OUTPUTS / 'ideal_baseline'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
