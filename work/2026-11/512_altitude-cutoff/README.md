---
title: "Where does PLAYONE hide high actors' shadows (the handbook's altitude cutoff)?"
started: 2026-11-16
issue: 512
outcome: "Narrowed: no height compare in PLAYONE's shadow draw (display-list run included) or STUNT.EXE's; live, high actors' shadows keep their plane and the view cull 0x1B0C drops them because their ground point is out of view. Open: a frame with a high actor whose ground point is in view, and one over raised ground."
---

# Where does PLAYONE hide high actors' shadows (the handbook's altitude cutoff)?

The record is [`journal.md`](journal.md); the findings live in [`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw) and [`stunt-exe/shadow.md`](../../../research/stunt-exe/shadow.md).
