"""Apply a CTP revision before that day's daily run.

Reads the configured revision sheet from the CTP workbook, hands it to
demand_manager.apply_revision() which updates open_demand + baseline_plan
using the rule:

    new_open_balance[sku] = revised_Updated_Requirement - cumulative_actuals[sku]

For SKUs not yet seen, cumulative_actuals = 0 → balance = revised qty.
"""
from __future__ import annotations

from V1.setups import input_loader
from V1.utilities import demand_manager


def apply(day_idx: int, sheet_name: str, cfg: dict) -> None:
    print(f"\n{'═'*70}\n  REVISION on Day {day_idx}  —  sheet: '{sheet_name}'\n{'═'*70}")
    revised = input_loader.load_demand_sheet(cfg["demand_file"], sheet_name)
    demand_manager.apply_revision(revised)
