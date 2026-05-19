"""Atomic read/write of state CSVs in state/.

Every write goes to a temp file in the same directory, then atomically
renames over the target. A crashed run can't leave a half-written state file.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from V1.config import settings


def _path(name: str) -> Path:
    return settings.STATE / f"{name}.csv"


def write_state(name: str, df: pd.DataFrame) -> None:
    settings.STATE.mkdir(parents=True, exist_ok=True)
    final = _path(name)
    fd, tmp = tempfile.mkstemp(prefix=f".{name}_", suffix=".csv", dir=settings.STATE)
    os.close(fd)
    df.to_csv(tmp, index=False)
    os.replace(tmp, final)


def read_state(name: str) -> pd.DataFrame:
    return pd.read_csv(_path(name))


def state_exists(name: str) -> bool:
    return _path(name).exists()


def clear_state() -> None:
    """Remove all state CSVs. Used by --reset."""
    if not settings.STATE.exists():
        return
    for p in settings.STATE.glob("*.csv"):
        p.unlink()
