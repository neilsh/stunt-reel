---
title: "research: why PLAYONE.EXE's archive load time changes the pages it draws"
started: 2026-11-18
issue: 609
outcome: "Loader read statically: every chunk is preloaded through an LRU chunk cache at a per-chunk cost, and the film clock starts on the first timer tick after the load. Why a later start changes the drawing is open."
---

# research: why PLAYONE.EXE's archive load time changes the pages it draws

A static reading of `PLAYONE.EXE`'s film and archive load, its chunk cache and the film clock's start; the log is [`journal.md`](journal.md), the finding is [`film-load.md`](../../../research/playone-exe/film-load.md), summarised in [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2.

## Handoff

Part 1 (the loader) is read: the load preloads every chunk, each costing a scan of the id table, a DOS open and close and, for ids from `0x8000` up, a walk of the MRU list; the `0x5B` and `0xF0` arms differ in that walk and in 8 own chunks evicted at load, so the 4-frame gap is not attributed.
Part 2 is partly read: the film clock starts on the first timer tick after the load, with no wait on a tick or the retrace; that tick being the quantum, what is stepped per drawn frame, and why the 63-chunk 4 MB arm starts later are open ([`film-load.md`](../../../research/playone-exe/film-load.md) open questions).
The live tick log the issue names needs DOSBox, which the cloud session lacks: [#722](https://github.com/neilsh/stunt-reel/issues/722); what is stepped per drawn frame is [#723](https://github.com/neilsh/stunt-reel/issues/723).
