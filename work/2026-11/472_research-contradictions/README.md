---
title: "docs(research): resolve contradictions across research notes and stale map.md/vm.rs claims"
started: 2026-11-13
issue: 472
outcome: "Seven contradictions from #307 plan Task 16 and two stale claims ruled on the evidence and fixed in place; the cause of the one-tick page lag is left open in the notes."
---

# Research contradictions

**Question.** For each contradiction plan Task 16 of [#307](../307_docs-streamline/plan.md) lists, and the two stale claims [#472](https://github.com/neilsh/stunt-reel/issues/472) adds, which side does the evidence support?

**Status.** One PR. The [journal](journal.md) holds one entry per item: the evidence read, the ruling, and the note that now holds it.

**Handoff.** Left open, in the notes: the cause of the one-tick page lag ([`dosbox-x-legacy.md`](../../../research/playone-exe/dosbox-x-legacy.md) open question 1). `vm.rs`'s `shade_level` subtracts 2 from `GVPOLY`/`GVPOLY16` levels on base `0x10`, which the handlers do not ([`sod-vm.md`](../../../research/playone-exe/sod-vm.md) open questions); a renderer change, not made here. Which build's opcode numbering `sod-opcodes.md` follows is [#480](https://github.com/neilsh/stunt-reel/issues/480). The `GVPOLY16` ramp word, left open at first, was traced in review (the journal's 2026-11-14 entries). The `memory-map.md` split (plan Task 16) can now start.
