---
title: "OP_PERFDISK 0xA05C sibling entry, non-BOMB normal depth scale, and OP_IPG type-6 streamer registers"
started: 2026-11-17
issue: 479
outcome: "Read and measured; no code change. OP_PERFDISK never perforates and no model in the data root uses a sliced op or OP_IPG type 6; type 6 takes BX = 6 and DX, BP from the previous handler; vm.rs matches the zero-normal skip; the current sphere winding beats the old one on LOCATION. Left: #689 (radius on other shapes, local-only) and #690 (renderer skips)."
---

# OP_PERFDISK 0xA05C sibling entry, non-BOMB normal depth scale, and OP_IPG type-6 streamer registers

What changed: [`sod-vm-generators.md` § 8.8](../../../research/playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators) and [`memory-map-vm.md`](../../../research/playone-exe/memory-map-vm.md); the evidence is in [`journal.md`](journal.md). Follow-ups: [#689](https://github.com/neilsh/stunt-reel/issues/689), [#690](https://github.com/neilsh/stunt-reel/issues/690).
