"""Compute end-of-study KPIs from the per-day simulation history.

The denominator for fulfillment is the **latest committed plan** — i.e. the
most recently applied demand revision (`state/baseline_plan.csv`). For a study
with revisions on Day 11 and Day 21 this is the 2nd iterative demand; with no
revisions it equals the Day-1 base demand. The frozen Day-1 base plan
(`state/original_plan.csv`) is still carried as a reference column / "vs
Original" row so the comparison against the ideal one-shot LP (which only ever
saw the Day-1 demand) is preserved.
"""
from __future__ import annotations

import pandas as pd

from V1.utilities import state_io


def _demand_basis() -> tuple[dict[str, int], dict[str, float], dict[str, int]]:
    """Return (latest_qty, latest_priority, original_qty) maps keyed by SKUCode.

    ``latest_*``   — the most recent committed plan (``baseline_plan.csv``,
                     rewritten by each applied revision; == base demand if no
                     revision ran). A SKU listed more than once in that sheet
                     is collapsed to its largest stated quantity (with that
                     row's priority).
    ``original_qty`` — the frozen Day-1 base demand (``original_plan.csv``).
    SKUs that existed in the Day-1 plan but were dropped from the final
    revision keep their original ask as the "latest" target (the wrapper keeps
    producing them, so we keep measuring them).
    """
    op = state_io.read_state("original_plan")
    original_qty = {str(r["SKUCode"]): int(round(float(r["Original_Quantity"])))
                    for _, r in op.iterrows()}
    original_prio = {str(r["SKUCode"]): float(r["Original_Priority"])
                     for _, r in op.iterrows()}

    if state_io.state_exists("baseline_plan"):
        bp = (state_io.read_state("baseline_plan")
              .sort_values("Baseline_Quantity", ascending=False)
              .drop_duplicates("SKUCode", keep="first"))
        latest_qty = {str(r["SKUCode"]): int(round(float(r["Baseline_Quantity"])))
                      for _, r in bp.iterrows()}
        latest_prio = {str(r["SKUCode"]): float(r["Priority"]) for _, r in bp.iterrows()}
    else:
        latest_qty, latest_prio = dict(original_qty), dict(original_prio)

    for sku, q in original_qty.items():
        latest_qty.setdefault(sku, q)
        latest_prio.setdefault(sku, original_prio[sku])
    return latest_qty, latest_prio, original_qty


def _avg_sku_fulfilment(actual_by_sku: dict, demand_by_sku: dict) -> float:
    """Headline fulfillment metric = simple arithmetic mean of per-SKU
    (actual / demand × 100) across SKUs with positive demand. Each SKU
    contributes equally regardless of size. Per-SKU percentages are NOT
    capped at 100 % — over-produced SKUs carry their actual ratio into the
    average. SKUs absent from ``actual_by_sku`` contribute 0 %.
    """
    pcts = []
    for sku, d in demand_by_sku.items():
        if d <= 0:
            continue
        a = float(actual_by_sku.get(sku, 0) or 0)
        pcts.append(a / float(d) * 100.0)
    if not pcts:
        return 0.0
    return round(sum(pcts) / len(pcts), 2)


def build_simulated_demand_fulfillment(history: dict) -> pd.DataFrame:
    """Per-SKU table mirroring the LP's Demand Fulfillment sheet.

    ``Demand`` is the **latest committed quantity** (last applied revision);
    ``Original_Demand`` carries the frozen Day-1 ask for reference.
    ``Actual_Units`` is the simulated cumulative production, and Gap / % /
    Status are computed against ``Demand`` (the latest committed quantity).
    """
    latest_qty, latest_prio, original_qty = _demand_basis()
    cum = state_io.read_state("cumulative_actuals")
    cum_map = dict(zip(cum["SKUCode"].astype(str), cum["Cumulative_Actual"]))

    ideal_sum = history["ideal"]["demand_fulfillment"].set_index("SKUCode") \
        if not history["ideal"]["demand_fulfillment"].empty else pd.DataFrame()

    # Authoritative maps from the masters — covers every schedulable SKU,
    # including ones added by a revision that the ideal one-shot never saw
    # (those would otherwise read Eligible_Machines = 0 / CycleTime_min = 0
    # because the ideal demand_fulfillment sheet has no row for them).
    masters = history.get("masters") or {}
    df_allow_m = masters.get("allowable")
    df_cycles_m = masters.get("cycles")
    elig_map: dict[str, int] = {}
    if df_allow_m is not None:
        for _, r in df_allow_m.iterrows():
            m = r.get("Machines")
            if isinstance(m, (list, tuple)):
                elig_map[str(r["SKUCode"]).strip()] = len(m)
    cycle_map: dict[str, float] = {}
    if df_cycles_m is not None:
        for _, r in df_cycles_m.iterrows():
            cycle_map[str(r["SKUCode"]).strip()] = float(r["CycleTime_min"])

    rows = []
    for sku in sorted(latest_qty):
        d = int(latest_qty[sku])
        prio = float(latest_prio[sku])
        orig_d = int(original_qty.get(sku, 0))
        actual = int(cum_map.get(sku, 0))
        gap = max(d - actual, 0)
        pct = round(actual / d * 100, 1) if d > 0 else 100.0
        # Eligible_Machines + CycleTime_min from masters (ground truth);
        # Status / Skip_Reason are LP-determined, so read from the ideal sheet.
        elig = int(elig_map.get(sku, 0))
        ct = float(cycle_map.get(sku, 0.0))
        status_src = ""
        skip = ""
        if not ideal_sum.empty and sku in ideal_sum.index:
            status_src = ideal_sum.loc[sku].get("Status", "")
            skip = ideal_sum.loc[sku].get("Skip_Reason", "")
            # Belt-and-braces: if masters somehow missed this SKU but the ideal
            # sheet has it, fall back so the field isn't blank.
            if not elig and "Eligible_Machines" in ideal_sum.columns:
                elig = int(ideal_sum.loc[sku].get("Eligible_Machines", 0) or 0)
            if not ct and "CycleTime_min" in ideal_sum.columns:
                ct = float(ideal_sum.loc[sku].get("CycleTime_min", 0) or 0)
        if status_src == "UNSCHEDULABLE":
            status = "UNSCHEDULABLE"
        elif gap <= 0:
            status = "FULLY MET"
        elif actual > 0:
            status = "PARTIAL"
        else:
            status = "UNMET"
        rows.append({
            "SKUCode":         sku,
            "Priority":        prio,
            "Demand":          d,
            "Original_Demand": orig_d,
            "Actual_Units":    actual,
            "Gap":             gap,
            "Fulfillment_Pct": pct,
            "Status":          status,
            "CycleTime_min":   ct,
            "Eligible_Machines": elig,
            "Skip_Reason":     skip,
        })
    return pd.DataFrame(rows).sort_values("Priority", ascending=False).reset_index(drop=True)


def build_simulated_shift_schedule(history: dict) -> pd.DataFrame:
    """Concatenate every day's TODAY-only production into one timeline.

    Each row carries BOTH the LP-scheduled qty and the post-factor actual
    qty so the conversion is visible. The factor column (% applied) lets
    you verify the math row-by-row: Actual_Qty = Scheduled_Qty * (1 + factor/100).
    """
    rows = []
    for p in history["per_day"]:
        actuals = p.get("today_actuals")
        if actuals is None or actuals.empty:
            continue
        df = actuals.copy()
        df["Date"] = p["day_date"]
        df = df.rename(columns={"Qty": "Scheduled_Qty"})
        df["Factor_Pct"] = (df["factor"] * 100).round(2)
        rows.append(df[["Date", "Machine", "SKUCode", "StartTime", "EndTime",
                        "Scheduled_Qty", "Factor_Pct", "Actual_Qty"]])
    if not rows:
        return pd.DataFrame(columns=["Date", "Machine", "SKUCode", "StartTime",
                                     "EndTime", "Scheduled_Qty", "Factor_Pct", "Actual_Qty"])
    out = pd.concat(rows, ignore_index=True)
    # The LP's shift schedule stores Machine inconsistently across row types
    # (some rows as int 14801, some as str '14801', some as float 14801.0).
    # Normalise to one canonical string so a single press collapses to a single
    # row in the Machine Schedule / Machine Utilization sheets — otherwise it
    # gets split (e.g. 170 presses → 245 rows, dragging the avg utilization down
    # with phantom near-zero rows). Mirrors the LP's own `_build_util`, which
    # casts Machine to int64 before grouping.
    out["Machine"] = (out["Machine"].astype(str).str.strip()
                      .str.replace(r"\.0+$", "", regex=True))
    return out


def build_simulated_machine_schedule(history: dict) -> pd.DataFrame:
    """Aggregate cycles + units per (Machine, SKU) across all simulated days."""
    df = build_simulated_shift_schedule(history)
    if df.empty:
        return pd.DataFrame(columns=["Machine", "SKUCode", "Cycles", "Units_Planned", "Mins_Used"])
    df["Mins_Used"] = (pd.to_datetime(df["EndTime"]) -
                       pd.to_datetime(df["StartTime"])).dt.total_seconds() / 60
    grp = df.groupby(["Machine", "SKUCode"], as_index=False).agg(
        Actual_Units=("Actual_Qty", "sum"),
        Mins_Used=("Mins_Used", "sum"),
    )
    grp["Actual_Cycles"] = (grp["Actual_Units"] / 2).round().astype(int)
    return grp[["Machine", "SKUCode", "Actual_Cycles", "Actual_Units", "Mins_Used"]].sort_values(
        ["Machine", "SKUCode"]
    ).reset_index(drop=True)


def build_simulated_machine_utilization(history: dict, planning_days: int) -> pd.DataFrame:
    """Per-machine total used minutes across the simulation.

    Available_Mins = simulation_days × 3 shifts × 8h × 60. (Same shape the LP uses.)
    """
    df = build_simulated_shift_schedule(history)
    if df.empty:
        return pd.DataFrame(columns=["Machine", "Available_Mins", "Used_Mins",
                                     "Idle_Mins", "Utilization_Pct", "Actual_Total_Units"])
    df["Mins_Used"] = (pd.to_datetime(df["EndTime"]) -
                       pd.to_datetime(df["StartTime"])).dt.total_seconds() / 60
    grp = df.groupby("Machine", as_index=False).agg(
        Used_Mins=("Mins_Used", "sum"),
        Actual_Total_Units=("Actual_Qty", "sum"),
    )
    sim_days = len(history["per_day"])
    avail = sim_days * 3 * 8 * 60
    grp["Available_Mins"] = avail
    grp["Idle_Mins"] = (avail - grp["Used_Mins"]).clip(lower=0)
    grp["Utilization_Pct"] = (grp["Used_Mins"] / avail * 100).round(2)
    return grp[["Machine", "Available_Mins", "Used_Mins", "Idle_Mins",
                "Utilization_Pct", "Actual_Total_Units"]].sort_values(
        "Utilization_Pct", ascending=False).reset_index(drop=True)


def count_simulated_changeovers_and_cleans(history: dict) -> tuple[int, int]:
    """Sum CHANGEOVER and MOULD_CLEAN rows that fell on each simulated day-1.

    Includes wrapper-forced rotations (which represent off-schedule changeovers
    inserted by the wrapper when a SKU finishes on a press).
    """
    co = 0
    cl = 0
    for p in history["per_day"]:
        lp = p.get("lp_results")
        if not lp:
            continue
        df = lp["shift_schedule"]
        if df is None or df.empty:
            continue
        df = df.copy()
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        today = df[df["Date"] == p["day_date"]]
        co += int((today["SKUCode"] == "CHANGEOVER").sum())
        cl += int((today["SKUCode"] == "MOULD_CLEAN").sum())
        co += int(p.get("forced_rotations", 0))
    return co, cl


def build_ideal_vs_simulated_kpi(history: dict) -> pd.DataFrame:
    """Side-by-side KPI comparison.

    Primary fulfillment basis is the **latest committed demand** (last applied
    revision). The Day-1 original basis is kept as a secondary row so the
    ideal one-shot LP — which only ever planned against the Day-1 demand —
    still has an apples-to-apples comparison. SKU status counts are reported
    against the latest committed demand for both columns; for the ideal column
    that means re-statusing its one-shot plan against the latest ask (SKUs the
    Day-1 plan never produced, e.g. SKUs added by a revision, count as UNMET).
    """
    ideal = history["ideal"]
    ideal_sum = ideal["demand_fulfillment"]
    ideal_util = ideal["machine_utilization"]
    ideal_shift = ideal["shift_schedule"]

    latest_qty, _latest_prio, original_qty = _demand_basis()
    latest_total = int(sum(latest_qty.values()))
    original_total = int(sum(original_qty.values()))

    ideal_planned = int(ideal_sum["Planned_Units"].sum()) if not ideal_sum.empty else 0
    ideal_avg_util = round(ideal_util["Utilization_Pct"].mean(), 2) \
        if not ideal_util.empty else 0
    ideal_co = int((ideal_shift["SKUCode"] == "CHANGEOVER").sum()) \
        if not ideal_shift.empty else 0
    ideal_cl = int((ideal_shift["SKUCode"] == "MOULD_CLEAN").sum()) \
        if not ideal_shift.empty else 0

    # Re-status the ideal one-shot plan against the LATEST committed demand.
    ideal_planned_by_sku = (dict(zip(ideal_sum["SKUCode"].astype(str), ideal_sum["Planned_Units"]))
                            if not ideal_sum.empty else {})
    ideal_unsch_skus = (set(ideal_sum.loc[ideal_sum["Status"] == "UNSCHEDULABLE", "SKUCode"].astype(str))
                        if not ideal_sum.empty else set())
    ideal_full = ideal_part = ideal_unmet = ideal_unsch = 0
    for sku, d in latest_qty.items():
        if sku in ideal_unsch_skus:
            ideal_unsch += 1
        elif d <= 0 or int(ideal_planned_by_sku.get(sku, 0)) >= d:
            ideal_full += 1
        elif int(ideal_planned_by_sku.get(sku, 0)) > 0:
            ideal_part += 1
        else:
            ideal_unmet += 1

    sim_sum = build_simulated_demand_fulfillment(history)
    sim_util = build_simulated_machine_utilization(history, history["cfg"]["planning_days"])

    sim_actual = int(sim_sum["Actual_Units"].sum())                          # all SKUs produced
    sim_actual_orig = int(sim_sum.loc[sim_sum["Original_Demand"] > 0, "Actual_Units"].sum())
    sim_avg_util = round(sim_util["Utilization_Pct"].mean(), 2) if not sim_util.empty else 0
    sim_co, sim_cl = count_simulated_changeovers_and_cleans(history)
    sim_full = int((sim_sum["Status"] == "FULLY MET").sum())
    sim_part = int((sim_sum["Status"] == "PARTIAL").sum())
    sim_unmet = int((sim_sum["Status"] == "UNMET").sum())
    sim_unsch = int((sim_sum["Status"] == "UNSCHEDULABLE").sum())

    # Fulfillment %: simple arithmetic mean of per-SKU (actual / demand × 100)
    # across SKUs with positive demand. Each SKU contributes equally regardless
    # of size — a 4-tyre micro-SKU at 0 % weighs the same as a 50,000-tyre SKU
    # at 100 %. NOT capped at 100 %, so over-produced SKUs (e.g. 102 %) carry
    # their full value into the average (per the literal "average of per-SKU
    # fulfillment %" definition the planner asked for).
    sim_actuals_by_sku = dict(zip(sim_sum["SKUCode"].astype(str), sim_sum["Actual_Units"]))
    ideal_pct_vs_original = _avg_sku_fulfilment(ideal_planned_by_sku, original_qty)
    sim_pct_vs_original   = _avg_sku_fulfilment(sim_actuals_by_sku,   original_qty)
    ideal_pct_vs_latest   = _avg_sku_fulfilment(ideal_planned_by_sku, latest_qty)
    sim_pct_vs_latest     = _avg_sku_fulfilment(sim_actuals_by_sku,   latest_qty)

    rows = [
        ("Total Demand — Original Day-1 Plan (units)",          original_total, original_total),
        ("Total Demand — Latest Revised Plan (units)",          latest_total,   latest_total),
        ("Output Units (Ideal=Planned, Simulated=Actual)",      ideal_planned,  sim_actual),
        ("Fulfillment % vs Original Day-1 Plan (avg across SKUs)",            ideal_pct_vs_original, sim_pct_vs_original),
        ("Fulfillment % vs Latest Revised Plan (avg across SKUs)  [PRIMARY]", ideal_pct_vs_latest,   sim_pct_vs_latest),
        ("Gap vs Latest Revised Plan (units)",                  latest_total - ideal_planned, latest_total - sim_actual),
        ("Avg Press Utilization %",                             ideal_avg_util, sim_avg_util),
        ("Total Changeovers (incl. wrapper-forced)",            ideal_co,      sim_co),
        ("Total Mould Cleans",                                  ideal_cl,      sim_cl),
        ("FULLY MET SKUs (vs Latest Revised Plan)",             ideal_full,    sim_full),
        ("PARTIAL SKUs (vs Latest Revised Plan)",               ideal_part,    sim_part),
        ("UNMET SKUs (vs Latest Revised Plan)",                 ideal_unmet,   sim_unmet),
        ("UNSCHEDULABLE SKUs",                                  ideal_unsch,   sim_unsch),
    ]
    df = pd.DataFrame(rows, columns=["Metric", "Ideal_Single_Shot", "Simulated_Daily_Rerun"])
    df["Delta"] = df["Simulated_Daily_Rerun"] - df["Ideal_Single_Shot"]
    return df


def build_per_day_history_sheet(history: dict) -> pd.DataFrame:
    rows = []
    for p in history["per_day"]:
        rows.append({
            "Day_Idx":           p["day_idx"],
            "Date":              p["day_date"].isoformat(),
            "Scheduled_Units":   p["today_scheduled"],
            "Actual_Units":      p["today_actual"],
            "Open_Balance_End":  p["open_after"],
            "Forced_Rotations":  p.get("forced_rotations", 0),
        })
    return pd.DataFrame(rows)


def load_forced_changeovers_log() -> pd.DataFrame:
    """Read the cumulative forced-rotations log written by daily_route."""
    if not state_io.state_exists("forced_changeovers_log"):
        return pd.DataFrame(columns=["Day_Idx", "Date", "Machine", "From_SKU", "To_SKU"])
    return state_io.read_state("forced_changeovers_log")


def build_changeover_breakdown(history: dict) -> pd.DataFrame:
    """Per-day breakdown of LP-scheduled vs wrapper-forced changeovers.

    LP-scheduled CO = CHANGEOVER rows in today's LP shift schedule that fall
    on the simulation day (these are mid-day swaps the LP itself planned).

    Forced CO = wrapper auto-rotations recorded in forced_changeovers_log
    (these happen between days when a SKU finishes and we mount a new SKU
    on the now-idle press).
    """
    forced = load_forced_changeovers_log()
    forced_by_day = (forced.groupby("Date").size().to_dict()
                     if not forced.empty else {})

    rows = []
    for p in history["per_day"]:
        lp_co = 0
        if p.get("lp_results") and not p["lp_results"]["shift_schedule"].empty:
            df = p["lp_results"]["shift_schedule"].copy()
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            today = df[df["Date"] == p["day_date"]]
            lp_co = int((today["SKUCode"] == "CHANGEOVER").sum())
        f_co = int(forced_by_day.get(p["day_date"].isoformat(), 0))
        rows.append({
            "Day_Idx":          p["day_idx"],
            "Date":             p["day_date"].isoformat(),
            "LP_Scheduled_CO":  lp_co,
            "Wrapper_Forced_CO": f_co,
            "Total_CO":         lp_co + f_co,
        })
    return pd.DataFrame(rows)
