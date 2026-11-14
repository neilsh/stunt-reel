---
title: "OP_PERFDISK draws nothing, though the corpus walk reaches it 2,531 times"
started: 2026-11-12
issue: 392
outcome: "OP_PERFDISK draws as a two-sided 16-gon disc from handler 0xA040 (sod-vm.md section 8.8, #424); BOMB rises 0.81291 to 0.81429 (+0.0014) and the worst reference fall is LAND (-0.0004)."
---

# OP_PERFDISK draws nothing, though the corpus walk reaches it 2,531 times

## Handoff

`OP_PERFDISK` draws as a two-sided 16-gon disc ([`sod-vm.md` § 8.8](../../../research/playone-exe/sod-vm.md#88-model-frame-the-other-generators)); the [journal](journal.md) has the read and the scores. Open: the radius's scale (the handler shifts by 16 where `OP_SPHERE` shifts by 8) and the normal's depth rescale by `0x8108`, the sibling entry `0xA05C`, which may bear on a perforation, the near-depth and shadow-pass skips, and a capture check of a disc's size.
