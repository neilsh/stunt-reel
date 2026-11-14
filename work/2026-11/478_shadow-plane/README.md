---
title: "Hero shadow plane (+0x1E/+0x22), altitude cutoff, camera slot shadow check, and 0x806C readers"
started: 2026-11-14
issue: 478
outcome: "Static reads: the probe 0x240A writes slot +0x1E (ground-leaf plane) and +0x20/+0x22 (code-8 box top) for SIF_MOVES slots; create 0x3CF2 stores type_flags at +1; 0x1C0D projects along world y; every 0x806C reader named. View-slot shadows and other renderer deltas filed as #499; the altitude cutoff stays open."
---

# Hero shadow plane (+0x1E/+0x22), altitude cutoff, camera slot shadow check, and 0x806C readers

Journal: [journal.md](journal.md). Findings live in [`sod-vm.md` § 9.1](../../../research/playone-exe/sod-vm.md#91-the-actor-shadow-draw); renderer follow-up in [#499](https://github.com/neilsh/stunt-reel/issues/499). Open: the handbook's altitude cutoff, a live frame of a view slot's shadow.
