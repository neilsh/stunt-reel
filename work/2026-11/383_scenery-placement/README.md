---
title: "Scenery placement module"
started: 2026-11-10
issue: 383
outcome: ""
---

# Scenery placement module

Move the SCENERY.scn walk with its LOD gate, dedup and the sub-pixel cull out of `world.rs` into
one module.
The module answers which props stand where, and why the walk stopped. Its tests go through that
interface only. [`spec.md`](spec.md) records the agreed decisions and what is left open.

Handoff: the spec is committed, and implementation has not started. Begin with the design-it-twice
step in the spec's "Left open" section, then the corpus "before" run.
