Place the following files here before running main.py:

REQUIRED (you provide):
  1. CTP demand workbook (Excel)
       - Default name: Apr_CTP_PCR_Requirement.xlsx
       - Sheet "Initial demand"           : Day 1 baseline
       - Sheet "Revised iteration 1 demand": Day 11 revision
       - (Add more "Revised iteration N demand" sheets for later revisions)
       - Columns: SKUCode, Base_Requirement, Updated_Requirement,
                  Order_Type, ConsolidatedPriorityScore

  2. Day-1 daily running moulds (CSV)
       - Default name: daily_running_moulds_day1.csv
       - Columns: WCNAME, Current MouldNo (LH#RH format), Sapcode,
                  SKU Description, Mould life, Target Life
       - "Mould life" = remaining cycles (used as-is)

AUTO-POPULATED (do not edit):
  inputs/masters/   -- on first run, main.py pulls cycle_times,
                       machine_allowable, gt_inventory, mould_master
                       from MySQL and caches them here. Subsequent
                       runs read from this cache.
                       Use --refresh-masters to force re-pull.
