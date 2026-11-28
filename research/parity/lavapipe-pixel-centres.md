---
summary: "#1099's vertex placement on pixel centres raised GPU-against-lavapipe pixel disagreement up to 13-fold; with it off, no film keeps any of the rise over the 2026-11-22 pin."
sidebar_label: "Lavapipe and pixel centres"
---
# Parity: Vertices on Pixel Centres and Class Agreement

* **Scope**: why the GPU and the canonical lavapipe draw more pixels differently since #1099 put every vertex on a pixel centre, measured for #1125; class agreement itself is [ADR 0055](../../docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md), the placement's `PLAYONE` rule is [`sod-vm-lines-spans.md` section 8.14](../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), and lavapipe's other differences are in [`lavapipe.md`](lavapipe.md).
* **Sources**: renders of the seven reference films on the RTX 4070 Laptop GPU and the canonical lavapipe under WSL 2, on `main` `459f46d2` with probe switches, compared on the 2026-11-26 agreement batch's tick sets.
* **Evidence tier**: stated at the start of each section.

## 1. The placement accounts for the whole rise

`[Bounded Observation]`, 2026-11-28, `crates` `2904ed01`, GPU driver 621.40, all seven films.
`playone_vertex` (`mode13h.wgsl`) moves each vertex to the centre of the pixel `PLAYONE`'s projector truncates it to, then along the ray through that centre to a plane through the vertex; `snap_edges`, #1197's copy for terrain, which landed after the batch's tree, moves only its x and y to that centre and keeps its depth.
With both returning the vertex's own projection, as before #1099, the mean differing index-plane pixels per tick fall to within 0.22 of the pin on six films, among them LAND 50.08 to 5.22 (pin 5.23), BALLOON 54.60 to 4.15 (4.12), INTRO 12.35 to 2.09 (2.25) and BOMB 20.89 to 8.43 (8.40); LOCATION, which had not risen, falls from 7.59 to 6.22 (8.60), and no film keeps a tick over 500 pixels.
`main` without the switch reproduces the batch's figures within 1.34 pixels a tick on a newer GPU driver, so with the placement off no film keeps any of its rise; each figure comes from one render per class, and the switch turns off #1099's placement and #1197's copy together.
The pixels are edge pixels: 99.8% of those at LAND 525 to 532 and on all of BALLOON have a 4-neighbour of another index on either class, and the scores agree: the batch's GPU-minus-lavapipe SSIM gaps are all inside the 0.002 bound.
_Source: [The rise is the pixel-centre vertex placement](../../work/2026-11/1125_class-agreement-regression/journal.md#2026-11-28-the-rise-is-the-pixel-centre-vertex-placement)._

## 2. Where the two classes still differ

`[Bounded Observation]`, 2026-11-28, LAND and BALLOON only.
`[Hypothesis]`: a vertex on a pixel centre puts the edges through it on sample points, where coverage depends on each rasterizer's tie rule and on how it rounds the vertex to its sub-pixel grid, so the two classes can cover the pixel differently.
Moving every placed vertex to `(0.5 + 5/256, 0.5 + 3/256)` within its pixel supports this for one kind of pixel only: BALLOON's differing pixels that are an actor on both classes fall from 42,676 to 3,499 over the film, while two others stay.

* **A thin actor** (LAND 520 to 540): pixels where one class draws an actor and the other does not, nearly all in rows 40 to 99 toward the view's right edge; LAND 531 differs by 715 pixels, and the offset leaves the range at 403.19 pixels a tick against 392.19.
* **A prop against the terrain under it** (BALLOON): 18,744 pixels over the film where one class draws a flat prop and the other the terrain, 18,623 with the offset.

The offset leaves LAND at 34.11 and BALLOON at 19.89 pixels a tick, and on the GPU it moves 243.00 and 176.92 pixels a tick of the render itself, so it is no fix as measured.
_Source: [Vertices off the pixel centre by (5, 3)/256 pixel](../../work/2026-11/1125_class-agreement-regression/journal.md#2026-11-28-vertices-off-the-pixel-centre-by-5-3256-pixel)._

## Ruled out

* **A GPU driver change or another renderer commit as the cause of the rise**: with the placement off (#1099's and #1197's copy), `main` on driver 621.40 keeps none of the rise on any of the seven films, on one render per class; [journal](../../work/2026-11/1125_class-agreement-regression/journal.md#2026-11-28-the-rise-is-the-pixel-centre-vertex-placement).
* **Grazing slides**: keeping a vertex's own projection when its slid point lies more than 4 times its distance from the eye moves LAND's and BALLOON's disagreement by 0.02 pixels a tick or less, alone or with the offset; [journal](../../work/2026-11/1125_class-agreement-regression/journal.md#2026-11-28-capping-grazing-slides-at-four-times-the-vertexs-distance).
* **A (5, 3)/256-pixel offset from the pixel centre as a fix**: it removes most same-layer actor pixels but leaves LAND and BALLOON at 6.5 and 4.8 times the pin; [journal](../../work/2026-11/1125_class-agreement-regression/journal.md#2026-11-28-vertices-off-the-pixel-centre-by-5-3256-pixel).

## Open questions

1. Whether to pin the higher disagreement over the flags with a recorded reason (`mise run agreement -- pin --accept`) or to change the placement; that is the owner's call under ADR 0055, on a fresh batch on `main` at or after `ff7f73b`, as the issue's 2026-11-27 comment asks.
2. What makes LAND's thin-actor pixels and BALLOON's prop-against-terrain pixels differ: a depth readout at LAND 531 and BALLOON 809 would tell a depth tie from a coverage rule.
3. The SSIM gaps on `main`: this note's renders were not scored, since the data root's LAND and BALLOON captures were replaced on 2026-11-28.
