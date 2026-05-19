"""Roll the running_moulds state from end-of-Day-N to start-of-Day-(N+1).

Inputs:
  - LP shift schedule for today (df_shift filtered to today's Date)
  - current running_moulds (read from state)
  - actuals factor per SKU for today (so mould-life decrement matches actuals, not schedule)
  - df_mould_master  : finds compatible moulds when a swap happens
  - df_allow         : machine-allowable matrix (SKU -> list of machines)
  - df_cycles        : cycle-times master (SKUCode / CycleTime_min)
  - day_idx          : 1-based index of the day just simulated
  - simulation_days  : total length of the study (for "days left in horizon")
  - target_life      : default 3000; cap after a mould clean / fresh mount
  - consolidation_*  : tail-consolidation policy knobs (see configs/<plant>.yaml)

Behaviour on SKU finish — TAIL-CONSOLIDATION policy (consolidation_enabled=True):
  - Presses whose running SKU still has open demand > 0 → kept unchanged
    (mould life decremented as before), no rotation.
  - Presses whose running SKU just finished (open balance hit 0), plus any
    press that produced nothing today (already idle), form the pool of
    "available" presses.
  - For every SKU with remaining open demand we compute the MINIMUM number of
    presses it needs to finish that demand within the remaining study horizon
    (work_min vs press-minutes left, with a slack factor; a small-demand
    shortcut pins it to 1 press; capped at the count of compatible presses).
    deficit(SKU) = max(0, min_presses − #still-running presses on that SKU).
  - Walking SKUs in priority order (highest ConsolidatedPriorityScore first)
    we assign up to `deficit` of the available presses that are compatible
    with the SKU (per df_allow), preferring a press whose currently-mounted
    mould pair is already valid for the new SKU (fewest physical swaps).
    Each assignment is one forced rotation, logged exactly as before.
  - Available presses left unassigned are dropped (left idle). We do NOT force
    a changeover just to avoid idleness, and we never proactively pull a
    still-running SKU off a press.

Behaviour when consolidation_enabled=False — legacy "never idle" policy:
  - When a press's running SKU finishes, force-mount the highest-priority
    compatible unmet SKU on it (forced rotation); only drop the press if no
    compatible unmet SKU exists.

Returns: (new_running_moulds_df, forced_rotations_list)
"""
from __future__ import annotations

import math

import pandas as pd

from V1.utilities import state_io

_DEFAULT_CYCLE_MIN = 20.0   # fallback if a SKU is missing from the cycle-times master


def _moulds_str_to_list(s) -> list[str]:
    if isinstance(s, list):
        return [str(x) for x in s]
    if pd.isna(s):
        return []
    return [x for x in str(s).split("|") if x]


def _moulds_list_to_str(lst) -> str:
    return "|".join(map(str, lst))


def load_running_moulds_for_lp() -> pd.DataFrame:
    """Read state and return the format the LP expects (MouldNos as list)."""
    df = state_io.read_state("running_moulds")
    df["MouldNos"] = df["MouldNos"].apply(_moulds_str_to_list)
    return df


def _build_allow_map(df_allow: pd.DataFrame) -> dict[str, set[str]]:
    if df_allow is None or df_allow.empty:
        return {}
    return {
        str(s): {str(m) for m in machines}
        for s, machines in zip(df_allow["SKUCode"], df_allow["Machines"])
    }


def _build_mould_valid_map(df_mould_master: pd.DataFrame) -> dict[str, set[str]]:
    """SKU -> set of mould numbers valid for it (from df_mould_master)."""
    if df_mould_master is None or df_mould_master.empty:
        return {}
    mould_col = "MouldNo" if "MouldNo" in df_mould_master.columns else "Mould"
    sku_col = "Matl.Code" if "Matl.Code" in df_mould_master.columns else "SKUCode"
    out: dict[str, set[str]] = {}
    for sku, mould in zip(df_mould_master[sku_col].astype(str).str.strip(),
                          df_mould_master[mould_col].astype(str)):
        out.setdefault(sku, set()).add(mould)
    return out


def _find_next_compat_unmet_sku(
    machine: str,
    open_demand: pd.DataFrame,
    df_allow: pd.DataFrame,
) -> str | None:
    """Return highest-priority unmet SKU compatible with this machine, else None."""
    if open_demand.empty or df_allow.empty:
        return None
    allow_map = _build_allow_map(df_allow)
    candidates = []
    for _, r in open_demand.iterrows():
        sku = str(r["SKUCode"])
        qty = int(r["Quantity"])
        if qty <= 0:
            continue
        if str(machine) in allow_map.get(sku, set()):
            candidates.append((sku, float(r.get("Priority", 0.0))))
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[1])
    return candidates[0][0]


def _pick_mould_pair(
    sku: str,
    df_mould_master: pd.DataFrame,
    fallback: list[str],
) -> list[str]:
    mould_col = "MouldNo" if "MouldNo" in df_mould_master.columns else "Mould"
    sku_col = "Matl.Code" if "Matl.Code" in df_mould_master.columns else "SKUCode"
    compat = df_mould_master[df_mould_master[sku_col].astype(str).str.strip() == sku]
    chosen = compat[mould_col].astype(str).head(2).tolist()
    if len(chosen) >= 2:
        return chosen[:2]
    return list(fallback)[:2] if fallback else chosen


def _min_presses_for_sku(
    open_qty: int,
    cycle_min: float,
    days_left: int,
    compat_count: int,
    single_press_threshold: float,
    slack: float,
) -> int:
    """Minimum #presses to finish `open_qty` within `days_left` days."""
    if compat_count <= 0:
        return 0
    if open_qty < single_press_threshold:
        return 1
    work_min = (open_qty / 2.0) * cycle_min            # 2 tyres per cycle
    cap_per_press = days_left * 24 * 60 * max(slack, 1e-9)
    if cap_per_press <= 0:
        return min(1, compat_count) or 1               # no time left — 1 press, capped
    n = max(1, math.ceil(work_min / cap_per_press))
    return min(n, compat_count)


def roll(
    df_shift_today: pd.DataFrame,
    open_demand_after: pd.DataFrame,
    actuals_factors: dict[str, float],
    df_mould_master: pd.DataFrame,
    df_allow: pd.DataFrame,
    df_cycles: pd.DataFrame | None = None,
    day_idx: int = 1,
    simulation_days: int = 30,
    target_life: int = 3000,
    consolidation_enabled: bool = True,
    consolidation_single_press_threshold: float = 1200.0,
    consolidation_slack: float = 0.9,
) -> tuple[pd.DataFrame, list[dict]]:
    """Compute tomorrow's running_moulds from today's schedule + actuals.

    Returns (new_df, forced_rotations) — the new running_moulds and a list
    of {Machine, From_SKU, To_SKU} dicts capturing every machine where we
    forced a rotation to a new SKU.
    """
    current = state_io.read_state("running_moulds")
    current["MouldNos"] = current["MouldNos"].apply(_moulds_str_to_list)
    open_map = dict(zip(open_demand_after["SKUCode"].astype(str),
                        open_demand_after["Quantity"]))

    df_shift_today = df_shift_today.copy()
    if not df_shift_today.empty:
        df_shift_today["Machine"] = df_shift_today["Machine"].astype(str)
        df_shift_today["StartTime"] = pd.to_datetime(df_shift_today["StartTime"])
        df_shift_today["EndTime"] = pd.to_datetime(df_shift_today["EndTime"])

    # ── First pass: classify every press in current running_moulds ────────────
    #   kept_rows         — presses that keep their SKU (open demand > 0)
    #   available         — presses freed up (SKU finished) or idle today
    #   running_by_sku    — count of kept presses currently mounting each SKU
    kept_rows: list[dict] = []
    available: list[dict] = []          # each: {"row": mrow, "last_sku": str|None}
    running_by_sku: dict[str, int] = {}
    forced_rotations: list[dict] = []

    for _, mrow in current.iterrows():
        mach = str(mrow["Machine"])
        events = (df_shift_today[df_shift_today["Machine"] == mach]
                  .sort_values("StartTime") if not df_shift_today.empty else df_shift_today)

        prod = events[~events["SKUCode"].isin(["CHANGEOVER", "MOULD_CLEAN"])] \
            if not events.empty else events
        cleans = events[events["SKUCode"] == "MOULD_CLEAN"] \
            if not events.empty else events

        if prod is None or prod.empty:
            # Idle today — keep mount under legacy policy; available pool under consolidation.
            if consolidation_enabled:
                available.append({"row": mrow, "last_sku": str(mrow["SKUCode"])})
            else:
                kept_rows.append({
                    "Machine": mach,
                    "SKUCode": str(mrow["SKUCode"]),
                    "MouldNos": _moulds_list_to_str(mrow["MouldNos"]),
                    "MouldLife_remaining": int(mrow["MouldLife_remaining"]),
                    "Num_Moulds": int(mrow["Num_Moulds"]),
                })
            continue

        last_sku = str(prod.iloc[-1]["SKUCode"])

        if open_map.get(last_sku, 0) <= 0:
            # SKU finished on this press.
            if consolidation_enabled:
                available.append({"row": mrow, "last_sku": last_sku})
                continue
            # Legacy "never idle": force-mount highest-priority compatible unmet SKU.
            next_sku = _find_next_compat_unmet_sku(mach, open_demand_after, df_allow)
            if next_sku is None:
                continue
            mould_nos = _pick_mould_pair(next_sku, df_mould_master, mrow["MouldNos"])
            forced_rotations.append({"Machine": mach, "From_SKU": last_sku, "To_SKU": next_sku})
            kept_rows.append({
                "Machine": mach,
                "SKUCode": next_sku,
                "MouldNos": _moulds_list_to_str(mould_nos),
                "MouldLife_remaining": target_life,
                "Num_Moulds": len(mould_nos) if mould_nos else int(mrow["Num_Moulds"]),
            })
            continue

        # SKU still has open demand — keep it, decrement mould life.
        factor = actuals_factors.get(last_sku, 0.0)
        if cleans is None or cleans.empty:
            sku_qty = int(prod[prod["SKUCode"] == last_sku]["Qty"].sum())
            actual_units = sku_qty * (1 + factor)
            base_life = (target_life if last_sku != str(mrow["SKUCode"])
                         else int(mrow["MouldLife_remaining"]))
            new_life = max(int(base_life - actual_units / 2), 0)
        else:
            last_clean_end = cleans.iloc[-1]["EndTime"]
            post = prod[prod["StartTime"] >= last_clean_end]
            post_qty = int(post[post["SKUCode"] == last_sku]["Qty"].sum())
            actual_post = post_qty * (1 + factor)
            new_life = max(int(target_life - actual_post / 2), 0)

        if last_sku == str(mrow["SKUCode"]):
            mould_nos = list(mrow["MouldNos"])
        else:
            mould_nos = _pick_mould_pair(last_sku, df_mould_master, mrow["MouldNos"])

        kept_rows.append({
            "Machine": mach,
            "SKUCode": last_sku,
            "MouldNos": _moulds_list_to_str(mould_nos),
            "MouldLife_remaining": new_life,
            "Num_Moulds": len(mould_nos) if mould_nos else int(mrow["Num_Moulds"]),
        })
        running_by_sku[last_sku] = running_by_sku.get(last_sku, 0) + 1

    # ── Consolidation re-assignment of the available pool ─────────────────────
    if consolidation_enabled and available:
        days_left = simulation_days - day_idx
        if days_left > 0:
            allow_map = _build_allow_map(df_allow)
            valid_moulds = _build_mould_valid_map(df_mould_master)
            cycle_map: dict[str, float] = {}
            if df_cycles is not None and not df_cycles.empty:
                cycle_map = {str(s): float(c)
                             for s, c in zip(df_cycles["SKUCode"], df_cycles["CycleTime_min"])}

            # SKUs with remaining demand, highest ConsolidatedPriorityScore first.
            demand_rows = [
                (str(r["SKUCode"]), int(r["Quantity"]), float(r.get("Priority", 0.0)))
                for _, r in open_demand_after.iterrows()
                if int(r["Quantity"]) > 0
            ]
            demand_rows.sort(key=lambda t: -t[2])

            avail_machs = {str(a["row"]["Machine"]) for a in available}
            assigned_machs: set[str] = set()

            for sku, qty, _prio in demand_rows:
                compat_machs = allow_map.get(sku, set())
                if not compat_machs:
                    continue
                min_p = _min_presses_for_sku(
                    open_qty=qty,
                    cycle_min=cycle_map.get(sku, _DEFAULT_CYCLE_MIN),
                    days_left=days_left,
                    compat_count=len(compat_machs),
                    single_press_threshold=consolidation_single_press_threshold,
                    slack=consolidation_slack,
                )
                deficit = max(0, min_p - running_by_sku.get(sku, 0))
                if deficit <= 0:
                    continue

                # Candidate available presses compatible with this SKU, not yet assigned.
                cands = [a for a in available
                         if str(a["row"]["Machine"]) in compat_machs
                         and str(a["row"]["Machine"]) not in assigned_machs]
                if not cands:
                    continue
                valid_set = valid_moulds.get(sku, set())

                def _needs_swap(a) -> bool:
                    moulds = [str(x) for x in a["row"]["MouldNos"]]
                    return not (moulds and valid_set and set(moulds).issubset(valid_set))

                # Prefer presses that need NO physical mould swap.
                cands.sort(key=_needs_swap)
                for a in cands[:deficit]:
                    mach = str(a["row"]["Machine"])
                    from_sku = a["last_sku"] if a["last_sku"] is not None else ""
                    if not _needs_swap(a):
                        mould_nos = [str(x) for x in a["row"]["MouldNos"]]
                        new_life = int(a["row"]["MouldLife_remaining"])
                        num_m = int(a["row"]["Num_Moulds"])
                    else:
                        mould_nos = _pick_mould_pair(sku, df_mould_master, a["row"]["MouldNos"])
                        new_life = target_life
                        num_m = len(mould_nos) if mould_nos else int(a["row"]["Num_Moulds"])
                    forced_rotations.append({"Machine": mach, "From_SKU": from_sku, "To_SKU": sku})
                    kept_rows.append({
                        "Machine": mach,
                        "SKUCode": sku,
                        "MouldNos": _moulds_list_to_str(mould_nos),
                        "MouldLife_remaining": new_life,
                        "Num_Moulds": num_m,
                    })
                    assigned_machs.add(mach)
                    running_by_sku[sku] = running_by_sku.get(sku, 0) + 1
                if assigned_machs >= avail_machs:
                    break
            # Available presses not assigned → dropped (left idle), nothing appended.

    new_df = pd.DataFrame(kept_rows, columns=[
        "Machine", "SKUCode", "MouldNos", "MouldLife_remaining", "Num_Moulds"
    ])
    state_io.write_state("running_moulds", new_df)
    return new_df, forced_rotations
