"""Open-demand bookkeeping.

Responsibilities:
  - Build df_demand input for the LP from current open_demand.csv
  - Decrement open balances by today's simulated actuals
  - Apply revisions on revision days (subtract cumulative actuals from
    revised plan; add new SKUs at full revised qty)

State files touched:
  state/open_demand.csv         (read+write)
  state/baseline_plan.csv       (read+write — for delta calc)
  state/cumulative_actuals.csv  (read+write)
"""
from __future__ import annotations

import pandas as pd

from V1.utilities import state_io


def build_demand_for_lp() -> pd.DataFrame:
    """Read open_demand.csv and shape it for the LP (SKUCode, Quantity, Priority)."""
    df = state_io.read_state("open_demand")
    df = df[df["Quantity"] > 0].copy()
    df["Quantity"] = df["Quantity"].round().astype(int)
    return df.reset_index(drop=True)


def decrement_open_demand(actuals_by_sku: dict[str, int]) -> pd.DataFrame:
    """Subtract today's simulated actuals from open_demand. Clip at zero.

    Returns the updated open_demand DataFrame.
    """
    df = state_io.read_state("open_demand")
    df["Quantity"] = df.apply(
        lambda r: max(int(r["Quantity"]) - int(actuals_by_sku.get(r["SKUCode"], 0)), 0),
        axis=1,
    )
    state_io.write_state("open_demand", df)

    cum = state_io.read_state("cumulative_actuals")
    for sku, qty in actuals_by_sku.items():
        if sku in cum["SKUCode"].values:
            cum.loc[cum["SKUCode"] == sku, "Cumulative_Actual"] += int(qty)
        else:
            cum = pd.concat(
                [cum, pd.DataFrame([{"SKUCode": sku, "Cumulative_Actual": int(qty)}])],
                ignore_index=True,
            )
    state_io.write_state("cumulative_actuals", cum)
    return df


def apply_revision(revised_df: pd.DataFrame) -> pd.DataFrame:
    """Apply a CTP revision to open_demand and baseline_plan.

    Rules (per user spec):
      - For each SKU in the revised sheet:
          new_open_balance = revised_Quantity - cumulative_actuals[sku]   (>= 0)
          priority         = revised_Priority
      - For SKUs only in revised (new SKUs): cumulative_actuals = 0, so
          new_open_balance = revised_Quantity.
      - SKUs in old baseline but missing from revised are intentionally
        deferred (not handled — surfaced as a warning if encountered).
      - baseline_plan is updated to the revised quantities (used for the
        next delta calc, even though we now operate on absolute values).

    ``revised_df`` must have columns SKUCode, Quantity, Priority.
    Returns the new open_demand DataFrame.
    """
    cum = state_io.read_state("cumulative_actuals")
    cum_map = dict(zip(cum["SKUCode"], cum["Cumulative_Actual"]))

    baseline = state_io.read_state("baseline_plan")
    old_skus = set(baseline["SKUCode"])
    new_skus = set(revised_df["SKUCode"])
    dropped = old_skus - new_skus
    if dropped:
        print(f"  [Revision] WARNING: {len(dropped)} SKU(s) in baseline but not in revised "
              f"sheet — keeping their current open balance unchanged. SKUs: {sorted(dropped)[:5]}...")

    rows = []
    for _, r in revised_df.iterrows():
        sku = r["SKUCode"]
        revised_qty = int(round(float(r["Quantity"])))
        produced = int(cum_map.get(sku, 0))
        new_balance = max(revised_qty - produced, 0)
        rows.append({
            "SKUCode": sku,
            "Quantity": new_balance,
            "Priority": float(r["Priority"]),
        })

    open_d = state_io.read_state("open_demand")
    kept_dropped = open_d[open_d["SKUCode"].isin(dropped)]
    new_open = pd.concat([pd.DataFrame(rows), kept_dropped], ignore_index=True)
    state_io.write_state("open_demand", new_open)

    new_baseline = revised_df.rename(columns={"Quantity": "Baseline_Quantity"})[
        ["SKUCode", "Baseline_Quantity", "Priority"]
    ]
    state_io.write_state("baseline_plan", new_baseline)

    n_new = len(set(revised_df["SKUCode"]) - old_skus)
    print(f"  [Revision] Applied: {len(revised_df)} SKUs in revision "
          f"({n_new} new) | total open balance: {new_open['Quantity'].sum():,}")
    return new_open
