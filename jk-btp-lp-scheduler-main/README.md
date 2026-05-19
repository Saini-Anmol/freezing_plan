# BTP Curing LP Scheduler — drop your code here

This folder is a **placeholder** for the BTP plant's curing LP scheduler. Drop the
BTP curing schedule code package inside this folder when you receive it.

## Where the freezing simulation expects to find it

The freezing-simulation wrapper at [`../freezing_simulation/`](../freezing_simulation/)
looks at `lp_module_path` in [`configs/btp.yaml`](../freezing_simulation/configs/btp.yaml).
The default value is:

```
lp_module_path: ../jk-btp-lp-scheduler-main
```

Once you drop the BTP code inside this folder, **update that path** to point
to the directory containing the file with the `JK_LP_Curing_Scheduler_v2`
class (or whatever it is called in BTP's version).

For comparison, the CTP layout is:

```
jk-ctp-lp-scheduler-main/
└── ctp/
    └── Curing/
        └── V1/
            └── jk_curing_lp_PCR.py        ← contains JK_LP_Curing_Scheduler_v2
```

If the BTP package follows the same internal structure, the config path
becomes:

```yaml
lp_module_path: ../jk-btp-lp-scheduler-main/btp/Curing/V1
```

## Required interface contract

The wrapper's [`V1/utilities/lp_adapter.py`](../freezing_simulation/V1/utilities/lp_adapter.py)
imports the LP via:

```python
from jk_curing_lp_PCR import (
    Config as LPConfig,
    MouldTracker,
    JK_LP_Curing_Scheduler_v2,
)
```

So the BTP package must expose:

| Symbol | Purpose |
|---|---|
| `Config` (class) | Static configuration with `PLANNING_DAYS`, `PLAN_DATE`, `DB_*` etc. |
| `MouldTracker` (class) | Has `load_from_df(df_mould_master, df_running)` |
| `JK_LP_Curing_Scheduler_v2` (class) | Has `.run(df_demand, df_cycles, df_allow, df_gt, tracker, df_running, plan_start)` returning a dict with keys `machine_schedule, shift_schedule, demand_fulfillment, machine_utilization, mould_tracker` |

If BTP's class names differ, either rename them in the BTP source or extend
`lp_adapter.py` to use a per-plant import map. Talk to whoever maintains the
wrapper before changing class names.

## After dropping the BTP code

1. Update `configs/btp.yaml` → `lp_module_path` to the BTP subpath
2. Drop the BTP demand workbook into `freezing_simulation/inputs/btp/`
3. Drop a Day-1 daily running moulds CSV into `freezing_simulation/inputs/btp/`
4. Update `configs/btp.yaml` → `demand_file` and `day1_moulds_file` to those names
5. Run `python3 main.py --plant btp --refresh-masters --smoke-test`
   - DB pull populates `inputs/btp/masters/`
   - LP runs once for Day 1 to verify wiring
6. If smoke passes: `python3 main.py --plant btp --reset` for the full study
