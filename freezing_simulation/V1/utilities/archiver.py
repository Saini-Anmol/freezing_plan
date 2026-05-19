"""Per-day audit archive under runs/YYYY-MM-DD/."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from V1.config import settings


def _day_dir(d: date) -> Path:
    p = settings.RUNS / d.isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def archive_day(
    day_date: date,
    day_idx: int,
    lp_results: dict,
    today_actuals_df: pd.DataFrame,
    actuals_factors: dict[str, float],
    open_demand_after: pd.DataFrame,
) -> None:
    """Write a snapshot of inputs/outputs for this simulation day."""
    out = _day_dir(day_date)

    if not lp_results.get("shift_schedule").empty:
        lp_results["shift_schedule"].to_csv(out / "lp_shift_schedule_30day.csv", index=False)
    if not lp_results.get("demand_fulfillment").empty:
        lp_results["demand_fulfillment"].to_csv(out / "lp_demand_fulfillment.csv", index=False)
    if not lp_results.get("machine_utilization").empty:
        lp_results["machine_utilization"].to_csv(out / "lp_machine_utilization.csv", index=False)

    today_actuals_df.to_csv(out / "today_actuals.csv", index=False)
    open_demand_after.to_csv(out / "open_demand_after.csv", index=False)

    with open(out / "actuals_factors.json", "w") as f:
        json.dump({sku: round(f_val, 6) for sku, f_val in actuals_factors.items()},
                  f, indent=2)

    summary = {
        "day_idx": day_idx,
        "day_date": day_date.isoformat(),
        "today_scheduled_units": int(today_actuals_df["Qty"].sum()) if not today_actuals_df.empty else 0,
        "today_actual_units": int(today_actuals_df["Actual_Qty"].sum()) if not today_actuals_df.empty else 0,
        "open_demand_remaining": int(open_demand_after["Quantity"].sum()),
        "skus_remaining": int((open_demand_after["Quantity"] > 0).sum()),
    }
    with open(out / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
