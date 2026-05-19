Drop BTP plant inputs here:

REQUIRED (you provide):
  1. BTP CTP demand workbook (Excel)
       - Suggested name: Apr_BTP_PCR_Requirement.xlsx
       - Same sheet structure as the CTP file:
            "Initial demand"            : Day 1 baseline
            "Revised iteration N demand": revisions
       - Same columns: SKUCode, Base_Requirement, Updated_Requirement,
                       Order_Type, ConsolidatedPriorityScore

  2. Day-1 daily running moulds (CSV)
       - Suggested name: daily_moulds_pcr_2026-04-01.csv
       - Same columns as CTP version:
           WCNAME, Current MouldNo (LH#RH format), Sapcode,
           SKU Description, Mould life (consumed cycles), Target Life

After placing files, edit configs/btp.yaml to reference these filenames.

AUTO-POPULATED (do not edit):
  inputs/btp/masters/   -- on first run, main.py --plant btp pulls
                           cycle_times, machine_allowable, gt_inventory,
                           mould_master from MySQL and caches them here.
                           Use --refresh-masters to force re-pull.
