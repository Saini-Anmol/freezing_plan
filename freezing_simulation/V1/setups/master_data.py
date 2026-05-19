"""Pull LP master data from MySQL once and cache as Excel under inputs/masters/.

Idempotent: subsequent runs skip the DB pull unless force=True.
The cache is loaded back as DataFrames in the exact format
JK_LP_Curing_Scheduler_v2.run() expects.
"""
from __future__ import annotations

import ast

import pandas as pd

from V1.config import settings
from V1.config.settings import add_lp_to_path

REQUIRED_FILES = [
    "cycle_times.xlsx",
    "machine_allowable.xlsx",
    "gt_inventory.xlsx",
    "mould_master.xlsx",
]


def cache_complete() -> bool:
    return all((settings.MASTERS / f).exists() for f in REQUIRED_FILES)


def refresh(cfg: dict, force: bool = False) -> None:
    if cache_complete() and not force:
        print(f"  [Masters] Cache present in {settings.MASTERS} — skipping DB pull")
        return

    add_lp_to_path(cfg["lp_module_path"])
    from sqlalchemy import create_engine
    from jk_curing_lp_PCR import Config as LPConfig, ETL

    print(f"  [Masters] Connecting to MySQL @ {LPConfig.DB_SERVER}/{LPConfig.DB_NAME}")
    engine = create_engine(
        f"mysql+pymysql://{LPConfig.DB_USER}:{LPConfig.DB_PASSWORD}"
        f"@{LPConfig.DB_SERVER}/{LPConfig.DB_NAME}"
    )
    etl = ETL(engine, cfg["tyre_type"])

    print("  [Masters] Pulling cycle_times")
    df_cycles = etl.load_cycle_times()
    print("  [Masters] Pulling machine_allowable")
    df_allow = etl.load_machine_allowable()
    print("  [Masters] Pulling gt_inventory")
    df_gt = etl.load_gt_inventory()
    print("  [Masters] Pulling mould_master")
    df_mould = etl.load_mould_master()

    settings.MASTERS.mkdir(parents=True, exist_ok=True)
    df_cycles.to_excel(settings.MASTERS / "cycle_times.xlsx", index=False)
    df_allow.to_excel(settings.MASTERS / "machine_allowable.xlsx", index=False)
    df_gt.to_excel(settings.MASTERS / "gt_inventory.xlsx", index=False)
    df_mould.to_excel(settings.MASTERS / "mould_master.xlsx", index=False)

    print(f"  [Masters] Cached 4 files in {settings.MASTERS}")


def load() -> dict[str, pd.DataFrame]:
    """Load cached master DataFrames in LP-compatible format.

    Returns dict with keys: cycles, allowable, gt, mould_master.
    """
    if not cache_complete():
        missing = [f for f in REQUIRED_FILES if not (settings.MASTERS / f).exists()]
        raise FileNotFoundError(
            f"Master cache incomplete. Missing: {missing}. "
            f"Run main.py with --refresh-masters to pull from DB."
        )

    df_cycles = pd.read_excel(settings.MASTERS / "cycle_times.xlsx")

    df_allow = pd.read_excel(settings.MASTERS / "machine_allowable.xlsx")
    df_allow["Machines"] = df_allow["Machines"].apply(
        lambda x: ast.literal_eval(x) if isinstance(x, str) else (x if isinstance(x, list) else [])
    )

    df_gt = pd.read_excel(settings.MASTERS / "gt_inventory.xlsx")

    df_mould = pd.read_excel(settings.MASTERS / "mould_master.xlsx")

    return {
        "cycles": df_cycles,
        "allowable": df_allow,
        "gt": df_gt,
        "mould_master": df_mould,
    }
