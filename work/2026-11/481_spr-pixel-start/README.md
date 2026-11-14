---
title: "Reconcile spr.ksy / spr.md byte-4 pixel start and trailer against PLAYONE.EXE 0x7DE6 byte-6 start"
started: 2026-11-13
issue: 481
outcome: "The game reads an .SPR image as width, height, an encoding word (0 raw, non-zero span-coded, 2 observed) and pixels from byte 6 with no trailer; PCX2SPR writes pixels from byte 4 with a zero trailer."
---

# Reconcile spr.ksy / spr.md byte-4 pixel start and trailer against PLAYONE.EXE 0x7DE6 byte-6 start
