---
summary: "Drawing CTRY's base geometry in draw order with no depth test, as PLAYONE's painter does, scores below the depth buffer: SSIM 0.9184 to 0.9082 with nodes sorted back to front and 0.9068 in walk order, with worse index agreement on 103 and 91 of 114 frames; on this evidence, revisiting SPEC 2.1 is not worth an ADR."
sidebar_label: "Painter order vs depth buffer"
---
# Parity: Painting in Draw Order Instead of a Depth Buffer

* **Scope**: whether drawing in `PLAYONE`'s order with no depth test, the painter [`render-model.md`](render-model.md) section 1 describes, would score better than our depth buffer, the question of #698.
  It measures the cheap form of that painter, on the GPU pipeline, not a CPU rasterizer.
* **Sources**: `mise run parity -- --films ctry --software-only` on 2026-11-18, cloud lavapipe, each variant a patch to `crates/stunt-render` gated by an environment variable and not landed; the reports' `per_frame` `index_agreement`; comparison sheets rendered on 2026-11-19 with the same variants as one `DBG_PAINTER` switch.
  _Source:_ [journal, 2026-11-19](../../work/2026-11/698_painter-order/journal.md#2026-11-19-comparison-sheets-of-the-two-painters), which keeps the switch as a diff.
* **Evidence tier**: `[Bounded Observation]`: one film, one adapter, one run each.

## 1. What was measured

Three renders of CTRY, scored against its pinned capture:

* **Depth buffer**: the shipped renderer.
* **Sorted painter**: the base pipeline compares `Always` instead of `Less` (standard depth; it still writes depth, so the `[I5]` decal pass tests against the surface painted last), and each model's base slices are drawn back to front by the distance from the eye to their node's box centre, in a fixed order on ties.
* **Walk-order painter**: the same `Always` base pipeline, each model's base slices in its node walk's forward order, depth first, so a later sibling is drawn over an earlier one.

Shortcuts common to both painters, each a way they differ from `PLAYONE`:
* Draws keep the renderer's order: the world, then view-facing props, then actors in `frame.actors` order, unsorted against each other or the world, since #680 has not traced the actors' bucket.
  An actor behind a building is therefore painted over it.
* Sorting is per node, not by `PLAYONE`'s scenery walk ([`world-scene.md`](../playone-exe/world-scene.md) section 1) or `sorton` planes.
* The ground pass, sky, level of detail, culling, shading and rasterisation are the shipped renderer's, so only the base pass's visibility rule changes.

## 2. Result

| Render | SSIM | IoU | Index agreement | Frames with better index agreement than the depth buffer |
|---|---|---|---|---|
| Depth buffer | 0.9184 | 0.9910 | 0.9161 | |
| Sorted painter | 0.9082 | 0.9910 | 0.9114 | 11 of 114 |
| Walk-order painter | 0.9068 | 0.9910 | 0.9074 | 22 of 114 |

The sorted painter is worse on the other 103 scored frames; the walk-order painter on 91, with one equal.
The added loss lies in the classes the base pass draws: props 0.0404, 0.0475, 0.0489; actors 0.0074, 0.0089, 0.0088; terrain 0.0117, 0.0132, 0.0133, in the table's order; sky and ocean do not move.

## 3. What the frames show

Four CTRY ticks: the painters' best frame, each painter's worst, and an actor beside a building.
Each sheet runs capture, depth buffer, sorted painter, walk-order painter.

* **Tick 837** ([sheet](../../work/2026-11/698_painter-order/images/ctry-837-painters.png)): a pillar and a red roof stand behind a near hillside, hidden in the capture and the depth buffer.
  The walk-order painter paints their faces over the hillside.
  The sorted painter covers the faces, but their outlines show through: the outline pipeline shares the base pass's depth state, so it too compares `Always` (`edge_pipeline` in `crates/stunt-render/src/pipeline.rs`).
* **Ticks 871 and 881** ([871](../../work/2026-11/698_painter-order/images/ctry-871-painters.png), [881](../../work/2026-11/698_painter-order/images/ctry-881-painters.png)): an explosion behind the same hillside.
  The capture and the depth buffer cut it off at the hillside's edge.
  Both painters draw it whole over the hillside, since actors and raster blits are drawn after the world, and both show the hidden roof through the hillside.
  This is the "actor painted over" shortcut of section 1.
* **Tick 804** ([sheet](../../work/2026-11/698_painter-order/images/ctry-804-painters.png), [crop](../../work/2026-11/698_painter-order/images/ctry-804-painters-crop.png)): the painters change 128 and 142 pixels of the index plane, and the three renders look alike.

Every visible difference is wrong occlusion: a farther object, or its outline, drawn over a nearer one.
None of the four sheets shows missing faces, a changed sky or ground, or a tie the painters resolve the way the capture does.
At ticks 837, 871 and 881 the depth buffer is the render closest to the capture; at 804 the three look alike.

## 4. Verdict

On this evidence, revisiting [`docs/SPEC.md`](../../docs/SPEC.md) section 2.1 is not worth an ADR: both painters lose to the depth buffer on CTRY by 0.0102 and 0.0115 SSIM, five times the 0.002 adoption margin or more, and on 103 and 91 of its 114 scored frames.
Where our draw order is not `PLAYONE`'s, the depth buffer still finds the nearer surface and a painter does not; a painter can gain only where its order matches `PLAYONE`'s, which needs the scenery walk and the actors' bucket traced first.
A CPU rasterizer would share the same order, so it was not wired to a film and is not kept.

Not measured: a crop at each tie issue's own frames (#698's third measure; the sheets above are picked by score instead), whether two painter runs write byte-identical planes, and INTRO.
