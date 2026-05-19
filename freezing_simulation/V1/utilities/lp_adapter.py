"""Single LP invocation — wraps JK_LP_Curing_Scheduler_v2.run().

Sets the LP's Config.PLANNING_DAYS / PLAN_DATE per call so the same LP
binary can be reused across daily simulations with different anchors.
Returns the LP's results dict (5 DataFrames).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from V1.config.settings import add_lp_to_path


def run_lp(
    df_demand: pd.DataFrame,
    df_cycles: pd.DataFrame,
    df_allow: pd.DataFrame,
    df_gt: pd.DataFrame,
    df_mould_master: pd.DataFrame,
    df_running: pd.DataFrame,
    plan_start: datetime,
    planning_days: int,
    lp_module_path: Path,
) -> dict:
    """Returns LP results dict with keys:
        machine_schedule, shift_schedule, demand_fulfillment,
        machine_utilization, mould_tracker
    """
    add_lp_to_path(lp_module_path)
    from jk_curing_lp_PCR import (
        Config as LPConfig,
        MouldTracker,
        JK_LP_Curing_Scheduler_v2,
    )

    LPConfig.PLANNING_DAYS = planning_days
    LPConfig.PLAN_DATE = plan_start

    tracker = MouldTracker()
    tracker.load_from_df(df_mould_master, df_running)

    scheduler = JK_LP_Curing_Scheduler_v2()
    return scheduler.run(
        df_demand,
        df_cycles,
        df_allow,
        df_gt,
        tracker,
        df_running,
        plan_start,
    )
