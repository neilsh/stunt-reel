---
title: "With the per-frame SP_1NODE gate, INTRO camera 1 loses SSIM on every scored tick"
started: 2026-11-11
issue: 403
outcome: "Recorded, no rendering change: the gate keeps INTRO's far power-line spans, whose MOVETO/ZLINETO lines our 0.03 m ribbons draw sub-pixel (#415); one-pixel-wide ribbons on those shapes lift all 17 camera 1 ticks above the pre-#402 render. No CTRY hill fin shows through the hills, in the capture or ours, at ticks 287, 298 and 309. Patch #3's gate matches the unpatched one."
---

# With the per-frame SP_1NODE gate, INTRO camera 1 loses SSIM on every scored tick

## Handoff

Done, in the [journal](journal.md), [`lod.md`](../../../research/playone-exe/lod.md) sections 1.2, 2.2, 4.2 and 4.4, and [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 6.2. Camera 1's loss is the power-line spans the gate now keeps, drawn with lines our renderer makes 0.03 m wide; the fix is [#415](https://github.com/neilsh/stunt-reel/issues/415), which now cites this case. Nothing in the renderer changed, so `references.toml` is unchanged. Left open: whether the gate picks the span `0x058C` or its stand-in `0x0590` where `PLAYONE` does; both draw two lines, so the frames cannot tell.
