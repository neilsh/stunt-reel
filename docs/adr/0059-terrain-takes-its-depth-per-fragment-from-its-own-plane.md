# Terrain takes its depth per fragment from its own plane

## Status

accepted 2026-11-28 for [#1197](https://github.com/neilsh/stunt-reel/issues/1197), on the owner's decision, which waives the adoption bar for this change (Consequences), and implemented the same day; its cost on a GPU was not measured before the merge (Consequences).
The prototype is a throwaway switch ([`DBG_FRAG_DEPTH.diff`](../../work/2026-11/1197_ctry-hill-flicker/switches/DBG_FRAG_DEPTH.diff)).
Departs from the rule of [`sod-vm-lines-spans.md` § 8.14](../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre) that every world-mesh vertex slides in the horizontal plane, for terrain patches.
It overrides the adoption rule of [`loop-rules.md`](../../.agents/skills/improving-render-parity/loop-rules.md), under which this change is a recorded negative (below).

## Context

`playone_vertex` moves each vertex to the pixel `PLAYONE` truncates it to and slides it along that pixel's ray to a plane through the vertex, so surfaces that shared a plane keep their depth ties (§ 8.14).
For a sloped terrain patch far from the eye and a little below it, the horizontal plane is met by a grazing ray, kilometres beyond the vertex, and the patch's foot loses to the face behind it on some ticks: `CTRY` ticks 286 to 366, where a hill flickers that the capture keeps (#1197).
[The journal](../../work/2026-11/1197_ctry-hill-flicker/journal.md) records six sweeps of per-vertex planes (a bound or clamp on the slide, steep terrain or every raised patch in its own plane, a mixed slide).
None keeps the hill, `land` 551, the ocean beside far raised terrain and the film means together: a corner needs the hill's plane at one pixel and the ground's at another, and one plane per vertex cannot give both.

## Decision

For terrain patches (scenery class 2) in the `Mode13h` look:

* **The vertex moves only its edges.**
  It keeps `main`'s snapped pixel, and `main`'s rule that a vertex whose ray misses the horizontal plane keeps its own projection and is not snapped; it keeps its own clip `z` and `w`.
* **Each fragment writes `frag_depth` from the patch's own plane.**
  The vertex stage passes the patch's eye-relative plane as a flat varying; the fragment intersects the ray through its pixel centre with it.
* **No farther than the ground plane along the same ray.**
  The depth is the nearer of that and the world-height-0 plane's.
* **Only the world's base draw writes `frag_depth`.**
  It draws through a pipeline of its own (`terrain_pipeline`, entry points `vs_terrain` and `fs_terrain`), so no decal loses its depth bias ([I5]) and no other draw loses early depth testing.
  The prototype wrote it from `fs_main` and `fs_main_plane` for every fragment, dropping that bias for decals.
* **A fragment finds its NDC point from an interpolated clip position**, not its framebuffer position, which the prototype used and which is wrong on a letterboxed page.
* The ocean, props, shapes and the other looks are untouched.

## Considered options

* **Plain per-fragment depth** (prototype modes 1 and 2).
  Matches the plain raised slide on `land` and `balloon` (−0.0012, −0.0018) with the same worst frames; the ocean beats a face's pixels at its foot wherever the snapped foot edge lies below the true foot.
  The depth method is not the cause of that; `[Hypothesis]` for the mechanism.
* **Clamped, sloped patches only** (mode 5) and **every terrain patch** (mode 3, re-run with `main`'s snapping rule).
  They score alike to four places; mode 3 is the simpler.
  Mode 3's first run snapped vertices `main` leaves unsnapped and lost `bomb` (20 frames, −0.0127), so a flat-patch carve-out was tried as mode 5, on an explanation the re-run does not support.
* **Clamped, the ocean per fragment too** (mode 4).
  Worse: 167 frames down more than 0.005.
* **A per-vertex plane or bound** (journal, six sweeps).
  Ruled out above.
* **Leave the flicker.**
  Costs nothing and keeps `main`'s scores; the hill blinks on alternate render ticks in a shot the capture shows steady.

## Consequences

`[Bounded Observation]`, lavapipe, the implementation against `main` ([journal](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-adr-0059-implemented-as-a-terrain-pipeline)), and the prototype's mode 3 re-run for the target frames ([journal](../../work/2026-11/1197_ctry-hill-flicker/journal.md#2026-11-28-per-fragment-depth-from-the-polygons-own-plane)):

* The hill is drawn on the three target frames pictured (298, 331, 364); the target frames' pooled SSIM rises 0.0097 (target index +0.0051), the worst target frame 0.0014.
* Film means: `ctry` +0.0018, `intro` +0.0016, `location` +0.0011, `balloon` −0.0002, `land`, `traintnl` and `bomb` −0.0000; mask IoU unchanged.
  In the prototype one frame of 297 fell by more than 0.005 (`location` 4104, −0.0072).
* **It does not pass the adoption rule**: no film reaches +0.002 (`ctry` comes within 0.0002) and the target index is under the +0.010 bar, so the rule calls it a negative to revert.
  The bar guards against circularity, a variant chosen by the frames the round picked ([`method.md` § 4.1](../../research/parity/method.md)).
  Here the gain is not a selection effect: every form of this issue reached about the same +0.005 on these frames, `[Hypothesis]` because the hill covers a small part of each frame.
  The owner waived the bar for a flicker fix that costs no film; the score is not read as evidence for the rule.
* **Cost not measured on a GPU.**
  Lavapipe renders `location` (300 ticks) in 5.58 s with and 5.59 s without the switch's `frag_depth` write.
  Writing `frag_depth` turns early depth testing off for the pipeline that writes it (general GPU behaviour); the GPU measurement on Legion is recorded in the journal when it lands.
* The clamp's claim that a raised face does not lose to the ground or ocean at its foot is `[Hypothesis]` beyond the frames scored: those surfaces are drawn first and the face tests `Greater`, so a tie loses, and the ground's depth is rasterised where the face's is per fragment.
* A terrain patch below world height 0 is drawn no farther than the ground plane, as if on it.
* The world-plane constant (the model matrix's translation `y`) assumes the world mesh's model matrix is a pure translation, which it is today (`eye_relative_matrix(eye, IDENTITY)` in `scene_renderer.rs`).
