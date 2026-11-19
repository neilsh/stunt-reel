---
title: "sod: pose scenery by the angle bank, and measure the frame spacing behind var 10's previous value"
started: 2026-11-19
issue: 681
outcome: "Measured across 31 archives (2,473 unique models): 54 execute ROT* (46 actor, 0 scenery, 0 view-facing, 8 unplaced), using only operands 0x14, 0x18 and 0x1A (0 uses of 0x10, 0x12 or 0x16); rendering code stays unchanged (#693 already measured frame spacing)."
---

# sod: pose scenery by the angle bank, and measure the frame spacing behind var 10's previous value

`stuntreel sod-census --rot` finds `54` stock `ROT*` shapes across the 31 retail, demo and FreeFlight archives, `0` scenery props (`SCENERY.scn` or `SCENERY1`..`SCENERY6.RES`), `0` view-facing shapes (`HEADER_FACES_VIEW`), and `0` uses of operands `0x10`, `0x12` or `0x16`.
Per Branch C of [`plan.md`](plan.md), rendering code stays unchanged and only actors draw posed from `AngleBank`.

- Plan: [`plan.md`](plan.md).
- Journal: [`journal.md`](journal.md).
- Findings: [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 5, [`sod-vm-execution.md`](../../../research/playone-exe/sod-vm-execution.md) § 8.7.
