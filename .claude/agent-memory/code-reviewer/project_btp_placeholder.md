---
name: BTP LP status (placeholder, not delivered)
description: BTP plant LP is currently a stub skeleton; CLAUDE.md says BTP code is pending. Reviews of plant-agnostic wrapper fixes must consider both CTP behavior and BTP placeholder behavior.
type: project
---

As of this review, `jk-btp-lp-scheduler-main/btp_curing.py` exists but is a placeholder skeleton (per CLAUDE.md: "BTP plant (LP code pending)"). `configs/btp.yaml` is a TEMPLATE with TBD demand-file paths. The same wrapper drives both plants via `--plant ctp|btp`, so plant-agnostic fixes need to be safe against the eventual BTP LP behavior.

Observations from the placeholder:
- `btp_curing.py:1013` emits Machine via `mach = str(row["Machine"])` in its `_build_continuity` analog — same pattern as CTP.
- `btp_curing.py:423` constructs Machine via `df[wcname_col].astype(str).str.replace(r"(LH|RH)$", "").str.strip()` — IDs are not guaranteed to be numeric strings, unlike CTP's plain-digit WCNAMEs.
- `btp_curing.py:319` forces `df['Machines']` elements to `int` via `lambda lst: list(map(int, lst))` — but that's the per-SKU eligibility lists, not the Machine column on shift_schedule.

**Why:** Cross-plant safety. CTP-only assumptions about Machine being numeric will misbehave on BTP if BTP machine IDs are alphanumeric. Same wrapper, same KPI code path.

**How to apply:**
- Any Machine-type normalization should use `astype(str)` rather than `pd.to_numeric` — string is the only type that round-trips for both plants.
- When the BTP LP code is finally delivered, re-verify that `_build_continuity` still uses `str(...)` and that `ScheduleBuilder._make_row` passes through the `Machine` value unchanged.
