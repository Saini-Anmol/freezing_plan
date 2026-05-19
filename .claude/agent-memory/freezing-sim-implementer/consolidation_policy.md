---
name: consolidation-policy
description: CLAUDE.md decision #2 was relaxed (May 2026) from "never idle" to a tail-consolidation policy in moulds_manager.roll
metadata:
  type: project
---

CLAUDE.md decision #2 ("auto-rotate when a SKU finishes on a press") was relaxed in May 2026 from the strict "never idle a press while a compatible unmet SKU exists" rule to a **tail-consolidation policy** in `V1/utilities/moulds_manager.roll()`.

**Why:** the old rule scattered the leftover demand of a few nearly-done SKUs across dozens of presses in the demand-drained last week of a study (BTP 31-day study: ~450 wrapper-forced changeovers, ~90 on Day 30 alone). The user explicitly authorised relaxing the decision.

**How it works now:** presses still running a SKU with open demand are kept; presses whose SKU just finished plus presses idle today form an "available" pool; each SKU with open demand gets a computed `min_presses` (work_min vs press-minutes left × slack; capped at compatible-press count; demand below `consolidation_single_press_threshold` ⇒ 1 press); available presses are re-assigned by descending `ConsolidatedPriorityScore` only up to `deficit = min_presses − #still-running`, preferring presses needing no physical mould swap; leftover available presses are dropped (left idle). `consolidation_enabled: false` restores the legacy behaviour exactly.

**Three config knobs** (in BOTH `configs/btp.yaml` and `configs/ctp.yaml`, read via `cfg.get` in `daily_route`): `consolidation_enabled` (true), `consolidation_single_press_threshold` (1200), `consolidation_slack` (0.9).

**BTP 31-day result vs old baseline:** total changeovers 552 → 263; avg util 87.83% → 92.83%; fulfillment vs latest 92.99% → 98.57%; fully-met/partial/unmet SKUs 69/28/2 → 77/18/4. The 4 unmet are all tiny SKUs (≤490 tyres) the LP itself never scheduled — the ideal one-shot LP also leaves 4 unmet, so it's not a wrapper regression; it's low-priority SKUs losing the press race (same contention semantics as before).

**How to apply:** if asked to tune the changeover/utilization trade-off, the lever is now these three knobs (and `consolidation_enabled: false` as the escape hatch), NOT `CHANGEOVER_PENALTY_WEIGHT` (still protected at 0.01).
