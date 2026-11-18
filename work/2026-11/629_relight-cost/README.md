---
title: "perf(render): relit actor vertex rewrites double a lavapipe render"
started: 2026-11-18
issue: 629
outcome: "Not planned (closed 2026-11-18): the relit actor vertex rewrite cost no measurable time on INTRO on the GPU, and a cloud session cannot tell its cost on lavapipe from run-to-run spread; the cloud measurement is in research/parity/lavapipe.md, Ruled out. Reopen if a workflow comes to depend on lavapipe's render time."
---

# perf(render): relit actor vertex rewrites double a lavapipe render

Journal: [`journal.md`](journal.md).

**Handoff.** A cloud session cannot measure this: on Ubuntu's lavapipe with 4 vCPUs, INTRO's render spreads by more between identical runs than mesa-dist-win's whole rewrite cost ([journal](journal.md)). The issue stays `local-only`: profile and time it on the RTX 4070 laptop's mesa-dist-win, as the issue body says.
