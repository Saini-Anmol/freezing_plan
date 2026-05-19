"""Read user-provided inputs: CTP demand workbook + Day-1 daily running moulds CSV."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_demand_sheet(ctp_file: Path, sheet_name: str) -> pd.DataFrame:
    """Read one demand sheet from the CTP/BTP demand workbook.

    Accepts either of the two known column-name variants seen in practice:
      CTP standard:  Updated_Requirement, ConsolidatedPriorityScore
      BTP iter-2:    Requirement,         PriorityScore
    Returns a DataFrame with normalised columns: SKUCode, Quantity, Priority.
    """
    df = pd.read_excel(ctp_file, sheet_name=sheet_name)
    df = df.rename(columns={
        "Updated_Requirement":        "Quantity",
        "Requirement":                "Quantity",
        "ConsolidatedPriorityScore":  "Priority",
        "PriorityScore":              "Priority",
    })
    missing = [c for c in ("SKUCode", "Quantity", "Priority") if c not in df.columns]
    if missing:
        raise ValueError(
            f"Demand sheet '{sheet_name}' in {ctp_file.name} is missing column(s): {missing}. "
            f"Available columns: {list(df.columns)}"
        )
    df = df[["SKUCode", "Quantity", "Priority"]].copy()
    df["SKUCode"] = df["SKUCode"].astype(str).str.strip()
    df = df[df["Quantity"] > 0]
    df["Quantity"] = df["Quantity"].round().astype(int)
    return df.reset_index(drop=True)


def load_day1_moulds(moulds_file: Path, target_life: int = 3000) -> pd.DataFrame:
    """Read Day-1 daily running moulds CSV.

    Two CSV formats are supported (auto-detected by column names):

    1. **CTP raw consumed-cycle format** — columns include ``WCNAME``,
       ``Current MouldNo`` (LH#RH-joined), ``Sapcode``, ``Mould life``
       (consumed cycles). Wrapper does the consumed→remaining conversion
       (``target_life − consumed``, clipped at 0), splits LH#RH, and groups
       by WCNAME.

    2. **LP-ready format** (BTP) — columns are exactly ``Machine``,
       ``SKUCode``, ``MouldNos`` (``|``-joined string), ``MouldLife_remaining``
       (already in remaining cycles), ``Num_Moulds``. Wrapper passes through
       with only a string→list deserialization for ``MouldNos``. This
       matches the output of ``ETL.load_running_moulds()`` saved to CSV.

    Output (both paths): Machine | SKUCode | MouldNos (list) | MouldLife_remaining | Num_Moulds
    """
    df = pd.read_csv(moulds_file)
    cols = set(df.columns)
    lp_ready = {"Machine", "SKUCode", "MouldNos", "MouldLife_remaining", "Num_Moulds"}.issubset(cols)

    if lp_ready:
        df["MouldNos"] = df["MouldNos"].astype(str).apply(
            lambda s: [x for x in s.split("|") if x and x.lower() != "nan"]
        )
        df["Machine"] = df["Machine"].astype(str)
        df["SKUCode"] = df["SKUCode"].astype(str).str.strip()
        df["MouldLife_remaining"] = df["MouldLife_remaining"].astype(int)
        df["Num_Moulds"] = df["Num_Moulds"].astype(int)
        return df[["Machine", "SKUCode", "MouldNos", "MouldLife_remaining", "Num_Moulds"]]

    raw_required = {"WCNAME", "Current MouldNo", "Sapcode", "Mould life"}
    missing = raw_required - cols
    if missing:
        lp_cols = ["Machine", "SKUCode", "MouldNos", "MouldLife_remaining", "Num_Moulds"]
        raise ValueError(
            f"Day-1 moulds CSV {moulds_file.name} is in an unrecognised format. "
            f"Expected either LP-ready columns {lp_cols} "
            f"or raw columns {sorted(raw_required)}. Missing: {sorted(missing)}. "
            f"Found: {sorted(cols)}"
        )

    df["Mould life"] = (target_life - df["Mould life"].astype(int)).clip(lower=0)

    parts = df["Current MouldNo"].astype(str).str.split("#", n=1, expand=True)
    df_lh = df.copy()
    df_lh["MouldNo"] = parts[0]
    df_rh = df.copy()
    df_rh["MouldNo"] = parts[1] if parts.shape[1] > 1 else None

    df_split = pd.concat([df_lh, df_rh], ignore_index=True)
    df_split = df_split[df_split["MouldNo"].notna()].copy()
    df_split["MouldNo"] = df_split["MouldNo"].astype(str).str.strip()
    df_split = df_split[df_split["MouldNo"] != ""]

    df_split["No"] = 1
    grouped = (
        df_split.groupby("WCNAME")
        .agg(
            SKUCode=("Sapcode", "first"),
            MouldNos=("MouldNo", list),
            MouldLife_remaining=("Mould life", "min"),
            Num_Moulds=("No", "count"),
        )
        .reset_index()
        .rename(columns={"WCNAME": "Machine"})
    )
    grouped["Machine"] = grouped["Machine"].astype(str)
    grouped["SKUCode"] = grouped["SKUCode"].astype(str).str.strip()
    return grouped[["Machine", "SKUCode", "MouldNos", "MouldLife_remaining", "Num_Moulds"]]
