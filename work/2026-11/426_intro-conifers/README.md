---
title: "INTRO's conifer field past the STUNT letters is sparser and fainter than the capture's"
started: 2026-11-12
issue: 426
outcome: "Cause found: PLAYONE fills polygon spans with both ends included, so each pine's sub-pixel sliver draws; per-frame shapes now draw polygon outlines one pixel wide (INTRO +0.0023, LOCATION -0.0009, no film down 0.002). World-mesh outlines left open for their memory cost."
---

# INTRO's conifer field past the STUNT letters is sparser and fainter than the capture's

In a crop of `INTRO` tick 3301 the conifers stand where the capture's do; each pine's light half is a sliver under a pixel wide, which `PLAYONE`'s inclusive span filler (`0x7571`) draws and a pixel-centre rasteriser drops. The renderer now outlines the polygons of the shapes it draws per frame. Journal: [journal.md](journal.md). Left open ([`sod-vm.md` § 10](../../../research/playone-exe/sod-vm.md#10-open-questions)): outlines on the world mesh, which score higher but cost about five times its vertices, and how `0xC9D4` rounds a row's ends.
