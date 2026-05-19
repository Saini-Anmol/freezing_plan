"""Apply the actuals random factor to today's scheduled production.

Per user spec: one independent random draw per SKU per day, uniform in
``[low_pct, high_pct]`` (default ``[-5%, +2%]``). The same factor applies
to all machines producing that SKU on that day.

Public API:
  draw_factors(skus, low_pct, high_pct, rng) -> {sku: factor}
  apply_to_scheduled(scheduled_df, factors) -> actuals_df
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_rng(seed: int | None) -> np.random.Generator:
    return np.random.default_rng(seed)


def draw_factors(skus: list[str], low_pct: float, high_pct: float,
                 rng: np.random.Generator) -> dict[str, float]:
    """Draw one factor per SKU, uniform in [low_pct, high_pct]."""
    draws = rng.uniform(low_pct, high_pct, size=len(skus))
    return {sku: float(f) for sku, f in zip(skus, draws)}


def apply_to_scheduled(scheduled_df: pd.DataFrame,
                       factors: dict[str, float]) -> pd.DataFrame:
    """Scale scheduled qty by (1 + factor[sku]) per row.

    ``scheduled_df`` must have columns SKUCode and Qty.
    Returns a new DataFrame with an added Actual_Qty column (rounded int, >=0).
    """
    out = scheduled_df.copy()
    out["factor"] = out["SKUCode"].map(factors).fillna(0.0)
    out["Actual_Qty"] = (out["Qty"] * (1 + out["factor"])).round().clip(lower=0).astype(int)
    return out
