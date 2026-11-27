---
title: "Can callgrind instruction counts on lavapipe gate perf changes without a quiet machine?"
started: 2026-11-27
issue: 1122
outcome: "Adopted: Valgrind counts of one span moved at most 0.07% between repeats (0.01% outside glibc's malloc and memmove), and put #951's 0.13% to 0.23% cuts at 10x to 40x that range; lavapipe-instruction-counts.md"
---

# Can callgrind instruction counts on lavapipe gate perf changes without a quiet machine?

The spike ran in a cloud session ([`journal.md`](journal.md)); its finding is [`lavapipe-instruction-counts.md`](../../../research/parity/lavapipe-instruction-counts.md).

## Handoff

- The WSL 2 `perf stat` check and the cross-machine count are `#1154`.
- Turning the count into a `mise run` task, a how-to and a perf-ticket gate is `#1156`.
- [`count.sh`](count.sh) is the spike's runner, not a task: it hard-codes the Ubuntu lavapipe ICD and the spans' flags.
