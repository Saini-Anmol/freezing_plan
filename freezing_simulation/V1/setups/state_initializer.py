"""Initialise state files at the start of a study.

Writes (under state/):
  - original_plan.csv     : the very first base demand — frozen denominator for KPIs
  - baseline_plan.csv     : the most recent CTP commitment (used for delta calc at next revision)
  - open_demand.csv       : current open balance per SKU (decremented daily by simulated actuals)
  - cumulative_actuals.csv: running total of simulated actuals per SKU
  - running_moulds.csv    : current mould state per machine (rolled each day)
  - sim_meta.csv          : study metadata — current_day, start_date
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from V1.utilities import state_io


def initialise(df_base_demand: pd.DataFrame, df_day1_moulds: pd.DataFrame,
               start_date: date) -> None:
    """Create all state files. Overwrites any existing state."""
    original = df_base_demand.rename(columns={
        "Quantity": "Original_Quantity",
        "Priority": "Original_Priority",
    })[["SKUCode", "Original_Quantity", "Original_Priority"]]
    state_io.write_state("original_plan", original)

    baseline = df_base_demand.rename(columns={"Quantity": "Baseline_Quantity"})[
        ["SKUCode", "Baseline_Quantity", "Priority"]
    ]
    state_io.write_state("baseline_plan", baseline)

    open_d = df_base_demand.copy()
    state_io.write_state("open_demand", open_d)

    cum = df_base_demand[["SKUCode"]].copy()
    cum["Cumulative_Actual"] = 0
    state_io.write_state("cumulative_actuals", cum)

    moulds = df_day1_moulds.copy()
    moulds["MouldNos"] = moulds["MouldNos"].apply(
        lambda lst: "|".join(map(str, lst)) if isinstance(lst, list) else str(lst)
    )
    state_io.write_state("running_moulds", moulds)

    meta = pd.DataFrame([{
        "current_day_idx": 1,
        "start_date":      start_date.isoformat(),
    }])
    state_io.write_state("sim_meta", meta)

    print(f"  [Init] State initialised: {len(original)} SKUs, "
          f"{len(moulds)} machines, start={start_date}")


def state_already_initialised() -> bool:
    return all(state_io.state_exists(n) for n in
               ("original_plan", "baseline_plan", "open_demand",
                "cumulative_actuals", "running_moulds", "sim_meta"))
