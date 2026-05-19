"""Aggregate scheduled quantity per SKU from the Shift Schedule sheet.

Reads the Excel file defined in config.yaml (or overridden via CLI),
filters rows by the Date column to the configured [start_date, end_date]
range (inclusive), groups by SKUCode, sums Qty, and writes a CSV with
columns [SKUCode, Total Quantity Scheduled].
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml", help="Path to YAML config")
    p.add_argument("--input", help="Override input Excel file")
    p.add_argument("--start", help="Override start date (YYYY-MM-DD)")
    p.add_argument("--end", help="Override end date (YYYY-MM-DD)")
    p.add_argument("--output", help="Override output CSV path")
    return p.parse_args()


def run(cfg: dict) -> pd.DataFrame:
    df = pd.read_excel(
        cfg["input_file"],
        sheet_name=cfg["sheet_name"],
        header=cfg["header_row"] - 1,  # pandas header is 0-indexed
    )

    df[cfg["date_column"]] = pd.to_datetime(df[cfg["date_column"]]).dt.normalize()
    start = pd.to_datetime(cfg["start_date"])
    end = pd.to_datetime(cfg["end_date"])

    mask = df[cfg["date_column"]].between(start, end, inclusive="both")
    filtered = df.loc[mask, [cfg["sku_column"], cfg["qty_column"]]]

    result = (
        filtered.groupby(cfg["sku_column"], as_index=False)[cfg["qty_column"]]
        .sum()
        .rename(columns={cfg["qty_column"]: "Total Quantity Scheduled"})
        .sort_values("Total Quantity Scheduled", ascending=False)
        .reset_index(drop=True)
    )
    return result


def main() -> None:
    args = parse_args()
    cfg = load_config(Path(args.config))

    for cli_key, cfg_key in [
        ("input", "input_file"),
        ("start", "start_date"),
        ("end", "end_date"),
        ("output", "output_file"),
    ]:
        if getattr(args, cli_key):
            cfg[cfg_key] = getattr(args, cli_key)

    result = run(cfg)
    result.to_csv(cfg["output_file"], index=False)
    print(f"Wrote {len(result)} SKUs to {cfg['output_file']}")
    print(f"Date range: {cfg['start_date']} to {cfg['end_date']} (inclusive)")
    print(f"Total scheduled qty: {result['Total Quantity Scheduled'].sum():,}")


if __name__ == "__main__":
    main()
