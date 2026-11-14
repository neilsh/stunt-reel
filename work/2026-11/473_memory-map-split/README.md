---
title: "docs(research): split research/playone-exe/memory-map.md by segment"
started: 2026-11-14
issue: 473
outcome: ""
---

# docs(research): split research/playone-exe/memory-map.md by segment

**Question.** How should [`memory-map.md`](../../../research/playone-exe/memory-map.md), at 52 KB against the 20 KB budget, be split by segment so that each file is under budget and every `[MEM-*]` anchor and inbound link still resolves?

**Status.** Planned: [`plan.md`](plan.md), executed by [`split_473.py`](split_473.py).
