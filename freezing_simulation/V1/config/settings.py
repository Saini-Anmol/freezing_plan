"""Loads configs/<plant>.yaml, resolves paths, exposes plant-scoped constants.

The four runtime path constants (MASTERS, STATE, RUNS, OUTPUTS) are scoped
per-plant — each plant gets its own subfolder so two studies never collide.

Other modules MUST access these as ``settings.STATE`` etc. (attribute on the
module), not via ``from V1.config.settings import STATE`` — otherwise the
import-time copy would not see the plant-scoping update done by load_config.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]      # freezing_simulation/
INPUTS = ROOT / "inputs"

DEFAULT_PLANT = "ctp"

MASTERS: Path = INPUTS / DEFAULT_PLANT / "masters"
STATE:   Path = ROOT / "state" / DEFAULT_PLANT
RUNS:    Path = ROOT / "runs" / DEFAULT_PLANT
OUTPUTS: Path = ROOT / "outputs" / DEFAULT_PLANT


def _scope_paths(plant: str) -> None:
    """Mutate module-level path constants to point to a plant's subfolders."""
    global MASTERS, STATE, RUNS, OUTPUTS
    MASTERS = INPUTS / plant / "masters"
    STATE   = ROOT / "state" / plant
    RUNS    = ROOT / "runs" / plant
    OUTPUTS = ROOT / "outputs" / plant


def load_config(plant: str = DEFAULT_PLANT, path: Path | None = None) -> dict:
    if path is None:
        path = ROOT / "configs" / f"{plant}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Config for plant '{plant}' not found at {path}. "
            f"Available configs: {sorted(p.stem for p in (ROOT / 'configs').glob('*.yaml'))}"
        )

    with open(path) as f:
        cfg = yaml.safe_load(f)

    cfg.setdefault("plant", plant)
    if cfg["plant"] != plant:
        raise ValueError(
            f"Plant mismatch: --plant={plant} but {path.name} has plant: {cfg['plant']}"
        )

    _scope_paths(plant)

    cfg["demand_file"] = (ROOT / cfg["demand_file"]).resolve()
    cfg["day1_moulds_file"] = (ROOT / cfg["day1_moulds_file"]).resolve()
    cfg["lp_module_path"] = (ROOT / cfg["lp_module_path"]).resolve()

    if isinstance(cfg["start_date"], str):
        cfg["start_date"] = datetime.strptime(cfg["start_date"], "%Y-%m-%d").date()

    revisions = cfg.get("revision_sheets") or []
    cfg["revision_by_day"] = {int(r["day"]): r["sheet"] for r in revisions}

    return cfg


def add_lp_to_path(lp_path: Path) -> None:
    p = str(lp_path)
    if p not in sys.path:
        sys.path.insert(0, p)


def ensure_dirs() -> None:
    for d in (INPUTS, MASTERS, STATE, RUNS, OUTPUTS):
        d.mkdir(parents=True, exist_ok=True)
