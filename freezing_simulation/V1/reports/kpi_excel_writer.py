"""Final KPI workbook — mirrors the LP's 5 sheets + adds 3 comparison sheets.

Sheets:
  1. Demand Fulfillment       (mirrored — latest revised demand vs. simulated cumulative; Day-1 original kept as reference)
  2. Machine Schedule         (mirrored — aggregated per Machine,SKU across study)
  3. Shift Schedule           (mirrored — concatenated daily Day-1 production timelines)
  4. Machine Utilization      (mirrored — across all simulated days)
  5. Mould Tracker            (mirrored — final mould state at end-of-study)
  6. Ideal vs Simulated KPI   (NEW — side-by-side comparison)
  7. Per-Day History          (NEW — daily scheduled/actual/open balance)
  8. Schedule Stability       (NEW — schedule-nervousness metric)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from V1.config import settings
from V1.reports import kpi_calculator, stability_tracker
from V1.utilities import state_io

NAVY = "1F3864"
TEAL = "1F6B75"
GREEN = "C6EFCE"
AMBER = "FFEB9C"
RED = "FFC7CE"
GREY = "F2F2F2"
WHITE = "FFFFFF"


def _fill(c: str) -> PatternFill:
    return PatternFill("solid", fgColor=c)


def _title(ws, text: str, sub: str, n_cols: int) -> None:
    ws.insert_rows(1)
    ws.insert_rows(1)
    cl = get_column_letter(n_cols)
    ws.merge_cells(f"A1:{cl}1")
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, name="Arial", size=13, color="FFFFFF")
    ws["A1"].fill = _fill(NAVY)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    ws.merge_cells(f"A2:{cl}2")
    ws["A2"] = sub
    ws["A2"].font = Font(italic=True, name="Arial", size=9, color="FFFFFF")
    ws["A2"].fill = _fill(TEAL)
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16


def _header_row(ws, row_idx: int, n_cols: int) -> None:
    for c in range(1, n_cols + 1):
        cell = ws.cell(row_idx, c)
        cell.font = Font(bold=True, name="Arial", size=10, color="FFFFFF")
        cell.fill = _fill(NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row_idx].height = 28


def _kpi_banner(history: dict, sim_sum: pd.DataFrame, sim_util: pd.DataFrame,
                co: int, cl: int) -> str:
    td = int(sim_sum["Demand"].sum())               # latest revised demand (KPI basis)
    od = int(sim_sum["Original_Demand"].sum())      # frozen Day-1 demand (reference)
    tp = int(sim_sum["Actual_Units"].sum())
    gap = td - tp
    # Fulfillment % is the simple average of per-SKU (actual / demand * 100)
    # across SKUs with positive demand — each SKU contributes equally. Mirrors
    # the metric on the Ideal vs Simulated sheet.
    pct_each   = sim_sum.loc[sim_sum["Demand"] > 0, ["Actual_Units","Demand"]]
    pct        = round((pct_each["Actual_Units"] / pct_each["Demand"] * 100).mean(), 1) if not pct_each.empty else 0
    pct_o_each = sim_sum.loc[sim_sum["Original_Demand"] > 0, ["Actual_Units","Original_Demand"]]
    pct_o      = round((pct_o_each["Actual_Units"] / pct_o_each["Original_Demand"] * 100).mean(), 1) if not pct_o_each.empty else 0
    avg = round(sim_util["Utilization_Pct"].mean(), 1) if not sim_util.empty else 0
    return (f"Latest Revised Demand: {td:,}  (Day-1 Original: {od:,})  |  Actual Produced: {tp:,}  |  "
            f"Gap vs latest: {gap:,}  |  Fulfillment vs latest: {pct}% (avg-of-SKUs)  (vs Day-1: {pct_o}%)  |  "
            f"Avg Util: {avg}%  |  Changeovers: {co}  |  Mould Cleans: {cl}")


def write(history: dict, output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = settings.OUTPUTS / history["cfg"]["final_report_name"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sim_sum = kpi_calculator.build_simulated_demand_fulfillment(history)
    sim_mach = kpi_calculator.build_simulated_machine_schedule(history)
    sim_shift = kpi_calculator.build_simulated_shift_schedule(history)
    sim_util = kpi_calculator.build_simulated_machine_utilization(
        history, history["cfg"]["planning_days"]
    )
    co, cl = kpi_calculator.count_simulated_changeovers_and_cleans(history)
    kpi_compare = kpi_calculator.build_ideal_vs_simulated_kpi(history)
    per_day_hist = kpi_calculator.build_per_day_history_sheet(history)
    stability = stability_tracker.build(history)
    forced_log = kpi_calculator.load_forced_changeovers_log()
    co_breakdown = kpi_calculator.build_changeover_breakdown(history)

    final_moulds = state_io.read_state("running_moulds")

    banner = _kpi_banner(history, sim_sum, sim_util, co, cl)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        cols1 = ["SKUCode", "Priority", "Demand", "Original_Demand", "Actual_Units", "Gap",
                 "Fulfillment_Pct", "Status", "CycleTime_min",
                 "Eligible_Machines", "Skip_Reason"]
        sim_sum[cols1].to_excel(writer, sheet_name="Demand Fulfillment", index=False)
        ws = writer.book["Demand Fulfillment"]
        _title(ws, "FREEZING SIM — DEMAND FULFILLMENT (vs Latest Revised Plan; Original = Day-1 ask)",
               banner, len(cols1))
        _header_row(ws, 3, len(cols1))
        for ci, w in enumerate([26, 10, 13, 15, 14, 10, 13, 14, 12, 16, 22], 1):
            ws.column_dimensions[get_column_letter(ci)].width = w
        status_col = cols1.index("Status") + 1
        for ri in range(4, ws.max_row + 1):
            st = str(ws.cell(ri, status_col).value)
            color = {"FULLY MET": GREEN, "PARTIAL": AMBER,
                     "UNMET": RED, "UNSCHEDULABLE": GREY}.get(st, WHITE)
            ws.cell(ri, status_col).fill = _fill(color)

        cols2 = ["Machine", "SKUCode", "Actual_Cycles", "Actual_Units", "Mins_Used"]
        sim_mach[cols2].to_excel(writer, sheet_name="Machine Schedule", index=False)
        ws2 = writer.book["Machine Schedule"]
        _title(ws2, "FREEZING SIM — MACHINE SCHEDULE (cumulative across study)",
               banner, len(cols2))
        _header_row(ws2, 3, len(cols2))
        for ci, w in enumerate([12, 26, 10, 14, 14], 1):
            ws2.column_dimensions[get_column_letter(ci)].width = w

        cols3 = ["Date", "Machine", "SKUCode", "StartTime", "EndTime",
                 "Scheduled_Qty", "Factor_Pct", "Actual_Qty"]
        sim_shift[cols3].to_excel(writer, sheet_name="Shift Schedule", index=False)
        ws3 = writer.book["Shift Schedule"]
        _title(ws3, "FREEZING SIM — SHIFT SCHEDULE",
               "Each row: Actual_Qty = Scheduled_Qty × (1 + Factor_Pct/100). Factor drawn uniformly per SKU per day in [-5%, +2%].",
               len(cols3))
        _header_row(ws3, 3, len(cols3))
        for ci, w in enumerate([12, 12, 26, 18, 18, 14, 12, 12], 1):
            ws3.column_dimensions[get_column_letter(ci)].width = w

        cols4 = ["Machine", "Available_Mins", "Used_Mins", "Idle_Mins",
                 "Utilization_Pct", "Actual_Total_Units"]
        sim_util[cols4].to_excel(writer, sheet_name="Machine Utilization", index=False)
        ws4 = writer.book["Machine Utilization"]
        _title(ws4, "FREEZING SIM — PRESS UTILIZATION", banner, len(cols4))
        _header_row(ws4, 3, len(cols4))
        for ci, w in enumerate([12, 16, 14, 14, 16, 14], 1):
            ws4.column_dimensions[get_column_letter(ci)].width = w
        # colour the Utilization_Pct cell: green ≥90%, amber 60–90%, red <60%
        util_col = cols4.index("Utilization_Pct") + 1
        for ri in range(4, ws4.max_row + 1):
            try:
                u = float(ws4.cell(ri, util_col).value or 0)
            except (TypeError, ValueError):
                u = 0.0
            ws4.cell(ri, util_col).fill = _fill(GREEN if u >= 90 else AMBER if u >= 60 else RED)

        final_moulds.to_excel(writer, sheet_name="Mould Tracker", index=False)
        ws5 = writer.book["Mould Tracker"]
        _title(ws5,
               "FREEZING SIM — FINAL MOULD STATE (end of study)",
               f"Machines mounted: {len(final_moulds)}",
               len(final_moulds.columns))
        _header_row(ws5, 3, len(final_moulds.columns))
        for ci, w in enumerate([12, 26, 30, 16, 12], 1):
            ws5.column_dimensions[get_column_letter(ci)].width = w

        kpi_compare.to_excel(writer, sheet_name="Ideal vs Simulated", index=False)
        ws6 = writer.book["Ideal vs Simulated"]
        _title(ws6, "FREEZING SIM — IDEAL vs SIMULATED KPI",
               "Ideal = single-shot Day-1 LP plan; Simulated = 30-day daily rerun with actuals. "
               "PRIMARY fulfillment basis = LATEST revised demand (the last applied revision); "
               "the Day-1 original basis is shown as a secondary row. SKU status counts are vs the latest revised demand. "
               "Fulfillment % rows = simple arithmetic mean of per-SKU (actual / demand * 100) across SKUs with positive demand — each SKU contributes equally regardless of size; per-SKU values are NOT capped at 100 %.",
               kpi_compare.shape[1])
        _header_row(ws6, 3, kpi_compare.shape[1])
        for ci, w in enumerate([46, 20, 24, 14], 1):
            ws6.column_dimensions[get_column_letter(ci)].width = w

        per_day_hist.to_excel(writer, sheet_name="Per-Day History", index=False)
        ws7 = writer.book["Per-Day History"]
        _title(ws7, "FREEZING SIM — DAILY HISTORY",
               f"{len(per_day_hist)} simulated days",
               per_day_hist.shape[1])
        _header_row(ws7, 3, per_day_hist.shape[1])
        for ci, w in enumerate([10, 14, 18, 16, 18, 18], 1):
            ws7.column_dimensions[get_column_letter(ci)].width = w

        stability.to_excel(writer, sheet_name="Schedule Stability", index=False)
        ws8 = writer.book["Schedule Stability"]
        _title(ws8, "FREEZING SIM — SCHEDULE STABILITY (LP-planned qty, not actuals)",
               "Compares today's LP-planned qty for a future date vs the prior day's LP-planned qty for the same future date. Future-date actuals don't exist yet.",
               max(stability.shape[1], 1))
        if stability.shape[1] > 0:
            _header_row(ws8, 3, stability.shape[1])
            for ci, w in enumerate([14, 14, 26, 14, 14, 14], 1):
                ws8.column_dimensions[get_column_letter(ci)].width = w

        co_breakdown.to_excel(writer, sheet_name="Changeover Breakdown", index=False)
        ws9 = writer.book["Changeover Breakdown"]
        total_lp = int(co_breakdown["LP_Scheduled_CO"].sum()) if not co_breakdown.empty else 0
        total_forced = int(co_breakdown["Wrapper_Forced_CO"].sum()) if not co_breakdown.empty else 0
        _title(ws9, "FREEZING SIM — CHANGEOVER BREAKDOWN",
               f"LP-Scheduled: {total_lp}  |  Wrapper-Forced (idle-machine pickup): {total_forced}  |  Total: {total_lp + total_forced}",
               max(co_breakdown.shape[1], 1))
        if co_breakdown.shape[1] > 0:
            _header_row(ws9, 3, co_breakdown.shape[1])
            for ci, w in enumerate([10, 14, 18, 22, 12], 1):
                ws9.column_dimensions[get_column_letter(ci)].width = w

        if not forced_log.empty:
            forced_log.to_excel(writer, sheet_name="Forced Rotations Log", index=False)
            ws10 = writer.book["Forced Rotations Log"]
            _title(ws10,
                   "FREEZING SIM — FORCED ROTATIONS LOG",
                   f"{len(forced_log)} rotations across the study (idle-press auto-pickup)",
                   forced_log.shape[1])
            _header_row(ws10, 3, forced_log.shape[1])
            for ci, w in enumerate([10, 14, 12, 26, 26], 1):
                ws10.column_dimensions[get_column_letter(ci)].width = w

    print(f"  [Report] KPI workbook written -> {output_path}")
    return output_path
