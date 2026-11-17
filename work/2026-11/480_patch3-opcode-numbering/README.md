---
title: "Unpatched vs Patch 3 .SOD VM dispatch table shift above 0x0333 (108 vs 107 slots)"
started: 2026-11-17
issue: 480
outcome: "Patch #3 re-encoded no .SOD stream (its SPRITES.RES holds none) and no census walk reaches an opcode above 0x0333 (2,425 unique models here, 3,432 in the 2026-11-12 census); the SOD.H names number the Patch #3 build, read from its handlers, and the unpatched build adds an unnamed 0x033C. CENSUS_SKIPS drops LETTER (int3 on both builds) and adds BLOKADD2D and CIRCLESL; census counts unchanged."
---

# Unpatched vs Patch 3 .SOD VM dispatch table shift above 0x0333 (108 vs 107 slots)

Which opcode numbering the shipped `.SOD` streams and `SOD.H` follow above `0x0333`, now that Patch #3's `PLAYONE.EXE` has one dispatch slot fewer. See [`journal.md`](journal.md).
