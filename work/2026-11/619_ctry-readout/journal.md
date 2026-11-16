# Journal

## 2026-11-16: Error readout of vault-ctry

**Question**: which kinds of error does the vision-model readout see on the current render of the `vault-ctry` Patch #3 reference ([#619](https://github.com/neilsh/stunt-reel/issues/619)), the seventh film of the readout in [`477_vault-attribution`](../477_vault-attribution/journal.md#2026-11-16-error-readout-on-the-patch-3-references), whose second grader pass was refused?

**Method**: `main` at `3a7afb76`, RTX 4070 (`adapter` NVIDIA GeForce RTX 4070 Laptop GPU). `mise run parity -- --films ctry` scored SSIM 0.9185, IoU 0.9910, 114 of 121 frames scored, no drift against `[ctry.expected.gpu]`. Then `mise run parity-bench -- errors-make --film ctry` (12 sheets, ticks 14 to 980, seed 1), two Haiku passes (one fresh subagent per brief), `errors-disputes`, a Sonnet tie-break on the disputed sheets, `errors-score` with no `--against` (no earlier `readout.json` exists in this checkout).

**Result**: the two Haiku passes gave the same 0 to 3 grade on 192 of 216 sheet-category cells, and the same 2-or-more verdict on 205 of 216; 8 of 12 sheets were disputed (some category clear in one pass and not the other) and went to the tie-break. Frames graded 2 or more of 12: `sea-band-wrong` 7 (ticks 14, 100, 452, 716, 804, 892, 980; the first Haiku pass alone gives 6 and the second 5, so the count does not rest on the tie-break). Every other category is 0 frames; the largest other means are `background-misregistration` 0.75 and `scenery-missing` 0.17. One `other` note, at tick 540: the render's cockpit has a black speck and the fuselage shading differs. On 2026-11-01 (older render, older capture) the readout graded `aircraft-shape-broken` 8, `aircraft-parts-missing` 8, `shadow-missing` 5 and `scenery-missing` 3 on this film; none of them reaches 2 frames now, but the two readouts did not grade the same frames, so the drop is a lead rather than a paired change.

**Verdict**: control (a measurement; no render change). `sea-band-wrong` at 7 frames is a finding by the 4-frame rule of [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 4, and the highest on any of the seven references.

**Lives in**: [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 7 and open question 4.
