---
title: "World-mesh polygons drop the sub-pixel slivers PLAYONE's inclusive filler always draws"
started: 2026-11-12
issue: 430
outcome: "World props now draw their polygon outlines as a line list over the world's own vertices (LOCATION +51.5 MB of indices, about 16 % longer render): every film up, BOMB +0.0051, LOCATION +0.0050. Conservative rasterization and terrain outlines scored lower and are ruled out."
---

# World-mesh polygons drop the sub-pixel slivers PLAYONE's inclusive filler always draws

The world mesh's props draw each polygon's outline as a `LineList` over their own vertices, the coverage `PLAYONE`'s inclusive spans add (`0x7571`). Journal: [journal.md](journal.md). Left open ([`sod-vm.md` § 10](../../../research/playone-exe/sod-vm.md#10-open-questions)): how `0xC9D4` rounds a row's ends, and whether terrain is filled the same way.
