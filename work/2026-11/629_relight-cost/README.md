---
title: "perf(render): relit actor vertex rewrites double a lavapipe render"
started: 2026-11-18
issue: 629
outcome: ""
---

# perf(render): relit actor vertex rewrites double a lavapipe render

Journal: [`journal.md`](journal.md).

**Handoff.** A cloud session cannot measure this: on Ubuntu's lavapipe with 4 vCPUs, INTRO's render spreads by more between identical runs than mesa-dist-win's whole rewrite cost ([journal](journal.md)). The issue stays `local-only`: profile and time it on the RTX 4070 laptop's mesa-dist-win, as the issue body says.
