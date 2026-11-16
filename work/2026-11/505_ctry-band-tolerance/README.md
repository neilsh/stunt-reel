---
title: "parity: ctry's background band breaks the strict rule; would a per-index tolerance restore intro and land sky bands?"
started: 2026-11-16
issue: 505
outcome: "ctry's band drops 237 (IoU 0.5402 to 0.5369 on tree 7aeabce); no per-index tolerance adopted, strict rule kept (probes.md section 3)."
---

# parity: ctry's background band breaks the strict rule; would a per-index tolerance restore intro and land sky bands?

Measurements and verdict: [journal](journal.md). Handoff: rederiving `ctry`'s band whole fails because our render draws its ground off layers 0 to 2; on tree `7aeabce` the strict rule also gives `traintnl` 164, which its committed row lacks (out of this issue's scope).
