"""Schedule-nervousness metric.

For each (Day, Future_Day_Offset, SKU), compares how many units the LP
allocated when planning that future day, across consecutive daily reruns.
A high "shift" value means the LP changed its mind — Day 5's plan for
Day 10 differs a lot from Day 6's plan for Day 10, indicating the
scheduled rerun is "nervous". A perfect rolling system would have
stability shift ~0 for nearby days and growing for distant days.

Output sheet: Stability_Index — per (target_day, day_planned, sku) the
absolute difference in scheduled qty vs. the *previous* daily rerun's
plan for the same target day.
"""
from __future__ import annotations

import pandas as pd


def build(history: dict) -> pd.DataFrame:
    rows = []
    prev_plan: dict[tuple, int] = {}
    for p in history["per_day"]:
        lp = p.get("lp_results")
        if not lp:
            continue
        df = lp["shift_schedule"]
        if df is None or df.empty:
            continue
        df = df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        prod = df[~df["SKUCode"].isin(["CHANGEOVER", "MOULD_CLEAN"])]
        plan = prod.groupby(["Date", "SKUCode"], as_index=False)["Qty"].sum()

        for _, r in plan.iterrows():
            key = (r["Date"], r["SKUCode"])
            prev_qty = prev_plan.get(key)
            if prev_qty is not None and r["Date"] != p["day_date"]:
                rows.append({
                    "Day_Planned":     p["day_date"].isoformat(),
                    "Target_Date":     r["Date"].isoformat(),
                    "SKUCode":         r["SKUCode"],
                    "Current_Qty":     int(r["Qty"]),
                    "Previous_Qty":    int(prev_qty),
                    "Abs_Shift":       int(abs(int(r["Qty"]) - int(prev_qty))),
                })
        prev_plan = {k: int(v) for k, v in zip(
            list(zip(plan["Date"], plan["SKUCode"])), plan["Qty"]
        )}
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "Day_Planned", "Target_Date", "SKUCode",
            "Current_Qty", "Previous_Qty", "Abs_Shift",
        ])
    return df.sort_values(["Day_Planned", "Target_Date", "Abs_Shift"],
                          ascending=[True, True, False]).reset_index(drop=True)
