---
title: "The GPU's memory and byte-identity after freeing the world mesh"
started: 2026-11-20
issue: 707
outcome: "At #706's parent and merge the RTX 4070 Laptop writes byte-identical stores for all seven reference films and its peak working set does not move, while peak private falls about 10 MiB; the figures are in research/parity/evidence-limits.md section 3."
---

# The GPU's memory and byte-identity after freeing the world mesh

The GPU half of [#645](https://github.com/neilsh/stunt-reel/issues/645), which #706 left open at
`2ecbad1`: the RTX 4070 Laptop's render stores and memory at #706's parent and its merge.
The method, figures and hashes are in [`journal.md`](journal.md), and the finding is in
[`research/parity/lavapipe-render-time.md` § 7](../../../research/parity/lavapipe-render-time.md#7-memory-per-worker).

## Handoff

Done: all 21 render-store files and the seven scores are byte-identical at `4c43baa` and
`2ecbad1`, and the GPU's peak working set, peak private bytes and VRAM are measured at both.

Left: two open questions in [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), what the ~0.7 GiB of peak private bytes above the peak working set holds and why the 2026-11-16 pair read 942 MB working set and 1,443 MB private.
