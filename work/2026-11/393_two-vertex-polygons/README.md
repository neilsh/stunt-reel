---
title: "A polygon with two vertices stops the SOD walk, cutting 0x7F24 and 0x7F34 to fragments"
started: 2026-11-11
issue: 393
outcome: "PLAYONE draws a two-vertex polygon as a thin line (static reading); vm.rs now draws it as a line instead of stopping, which clears census groups B to D; CTRY and INTRO score unchanged."
---

# A polygon with two vertices stops the SOD walk, cutting 0x7F24 and 0x7F34 to fragments

Two-vertex `POLYZ`, `GVPOLY` and `GVPOLY16` raised `MalformedPolygon` in `vm.rs`. [`journal.md`](journal.md) has the reading of `PLAYONE`'s handlers and the census and parity runs; the fact lives in [`sod-vm.md` § 8.9](../../../research/playone-exe/sod-vm.md#89-polygons-of-two-vertices) and [`sod-opcode-coverage.md`](../../../research/formats/sod-opcode-coverage.md).
