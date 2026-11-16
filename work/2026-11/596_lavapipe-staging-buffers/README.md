---
title: "Lavapipe renders spend their time allocating one staging buffer per draw"
started: 2026-11-15
issue: 596
outcome: "Adopted in #601: one uniform upload per frame instead of one per draw took lavapipe LOCATION ticks 12-300 from 150.5 s to 81.8 s, its render stores byte-identical there and on the GPU over every reference film's captured ticks; the remaining wait on lavapipe's command thread is in research/parity/lavapipe.md section 6."
---

# Lavapipe renders spend their time allocating one staging buffer per draw
