---
title: "Two-vertex SOD polygons draw as a 0.03 m world ribbon, where PLAYONE draws a one-pixel screen line"
started: 2026-11-11
issue: 415
outcome: "Adopted: SOD lines draw one Mode 13h pixel wide on screen; all seven reference films rise (+0.0008 to +0.0067)."
---

# Two-vertex SOD polygons draw as a 0.03 m world ribbon, where PLAYONE draws a one-pixel screen line

`ZLINETO` is read statically down to its Bresenham driver (`0x7511`), and the renderer now draws it and two-vertex polygons as one-pixel screen lines. Journal: [journal.md](journal.md). Left open: a zero-length line (one pixel in `PLAYONE`, nothing here), the pen as a register rather than a point, and the Patch #3 image's line path.
