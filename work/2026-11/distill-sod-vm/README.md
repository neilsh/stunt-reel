---
title: "Distill research/playone-exe/sod-vm.md"
started: 2026-11-12
outcome: "Dated score measurements moved to journal.md and two rejected readings listed under Ruled out; the note stays over budget because the rest is current reference, which needs a split by subject"
---
# Distill `sod-vm.md`

The note was 57,641 bytes, nearly three times the 20 KB budget (`mise run doc-health`, 2026-11-12), and the first `size` finding. The daily gardening routine distilled it: [`journal.md`](journal.md) holds each dated measurement verbatim, and the note keeps what each established, with a `_Source:` link.

Almost all of the note is undated reference: handler offsets, operand layouts and the execution model, each with its tier. Distilling removes little of it. Bringing the note under budget needs a split by subject, for example sections 8 and 9 into notes of their own, which moves the homes that code comments cite by section number (`vm.rs`, `world/mod.rs`, `light.rs`, `credits.rs`, `pipeline.rs`, `scene_renderer.rs`). That split is left to its own PR.
