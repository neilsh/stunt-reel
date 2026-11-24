---
summary: "Mesa's clipper can make the shade varying NaN; with the guard, local lavapipe scores within 0.002 of the GPU on all seven films. Eye-relative transforms, which take the eye's translation off each draw's matrix on the CPU, cut the per-tick difference by 46% to 84% on each film and shrink the four near-coplanar depth-tie residues to 17 pixels or fewer each; other ties remain. Reversed, infinite depth in `Depth24Plus` lowers it again on every film (LOCATION 62.0 to 29.8 pixels per tick); in `Depth32Float` it rose on five, and on all seven when re-measured after #904 and #922. Drawing LOCATION's castle green strip as a decal of its moat (#966) removed the strip-against-moat tie at LOCATION 3815 to 3830; the worst tick over 3812 to 3968 fell from 584 to 39 differing pixels. The screen-linear ratio `shade·w / w` makes the Gouraud polygons the clipper breaks draw the GPU's gradient (BALLOON 145 on `3a7afb76`: all 4,044 broken pixels match the GPU, 1,097 differing pixels in the frame become 7). Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` drew the same index planes on an AMD Ryzen under WSL 2 as on a cloud container's Intel Xeon, on all 20,621 ticks of one tree; mesa-dist-win 25.2.8 differs from it by at most 33 pixels a tick. Render time is in its own note."
---
# Parity: Rendering on Lavapipe

* **Scope**: how Mesa's software Vulkan driver, lavapipe, renders our frames differently from a GPU, and what the renderer does about it; how long a lavapipe render takes is in [`lavapipe-render-time.md`](lavapipe-render-time.md).
  Cloud sessions ([ADR 0039](../../docs/adr/0039-cloud-sessions-fetch-pinned-game-archives.md)) and CI ([ADR 0006](../../docs/adr/0006-ci-renders-on-lavapipe.md)) both render on it.
  The findings name the Mesa build they come from; three builds were measured: Ubuntu's `mesa-vulkan-drivers` 25.2.8 (`llvmpipe (LLVM 20.1.2, 256 bits)`, cloud, and since § 6 local-windows under WSL), and mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and 26.2.6 (`llvmpipe (LLVM 23.1.4, 256 bits)`) on the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md).
* **Sources**: Mesa source (`src/gallium/auxiliary/draw/draw_pipe_clip.c` at `mesa-25.2.8`, `mesa-26.2.6` and `main`; `src/gallium/drivers/llvmpipe/lp_context.c`), parity runs logged in [`log.md`](../../work/2026-10/parity-log/log.md) on 2026-11-07 and 2026-11-15, the #265 journal, #635's parity and residue runs of 2026-11-16, and #637's of 2026-11-20.
* **Evidence tier**: stated at the start of each section.

## 1. Near ground polygons drew palette index 0

`[Bounded Observation]`, 2026-11-07, on `9f04164`, Ubuntu's Mesa 25.2.8; fixed by a guard in `fragment_index`.
Rendered on lavapipe (a cloud session with no GPU; CI's adapter too, [ADR 0006](../../docs/adr/0006-ci-renders-on-lavapipe.md)), CTRY and INTRO scored 0.6446 and 0.6040 against the GPU rows' 0.8725 and 0.8273, with IoU identical.
The loss was in the props class: in 52 of 114 CTRY and 69 of 209 INTRO scored frames, large ground decals close to the eye (the field under the hero at CTRY 389-444, the sand at INTRO 1295-1506 and 2632-2786) drew palette index 0 over their whole area, while the same props far away drew their own index (CTRY 1257).
`fragment_index` in `mode13h.wgsl` rounds the `@interpolate(linear) shade` varying, and that varying arrived as NaN, which `u32(clamp(floor(NaN + 0.5), 0, 255))` turns into 0.
Ruled out at CTRY 422: the actor shadow draw (black with it off) and the decal depth bias (black with slope 0); also ruled out: crossing the near plane as the reason here (section 2).
`fragment_index` now falls back to the flat `palette_index` when `shade` is not finite (candidate (c), section 3; since #595 it first tries a `perspective` copy of `shade`, candidate (d), and since #635 the ratio `shade·w / w`, candidate (e)), and the GPU test `a_ground_polygon_under_a_low_eye_keeps_its_index` fails on lavapipe without it (25,866 of 51,840 ground pixels at index 0).
Capture, then lavapipe on `9f04164`, then with the guard on `72028d1`: [`ctry-422-lavapipe-nan-shade.png`](../../work/2026-11/lavapipe-nan-shade/images/ctry-422-lavapipe-nan-shade.png), [`intro-1495-lavapipe-nan-shade.png`](../../work/2026-11/lavapipe-nan-shade/images/intro-1495-lavapipe-nan-shade.png) ([`log.md`](../../work/2026-10/parity-log/log.md), 2026-11-07).

## 2. Mechanism: the clipper's screen-space weight is 0/0

`[Supported Inference]`: Mesa source read, its clipper replayed on the frame's own triangles, and a live NaN trap agree; no trap inside Mesa itself.
Mesa 25.2.8 (Ubuntu `25.2.8-0ubuntu0.24.04.4`) llvmpipe, under lavapipe, clips in software through the gallium `draw` module and turns the guard band off (`lp_context.c` line 339), so a triangle is clipped against x = w, x = -w, y = w, y = -w, then the half-z near plane, in that order (`draw_pipe_clip.c` `do_clip_tri`).
For each new vertex, `interp()` (`draw_pipe_clip.c` lines 183-209) interpolates perspective attributes with the 3D weight `t`, but `noperspective` ones with a screen-space weight `t_nopersp = (dst_x/dst_w - out_x/out_w) / (in_x/in_w - out_x/out_w)`.
It picks the axis by testing the clip-space x of the endpoints for inequality, then divides by their screen-space difference.
An edge that an earlier pass left lying on a side plane x = ±w has both endpoints at screen x ±1, so the divisor is 0.
If that edge reaches behind the eye, the opposite x plane cuts it at w = 0, x = 0, and `dst_x/dst_w` is 0/0.
Either way `t_nopersp` is not finite, and `LINTERP(t, a, a) = a + t * 0` is NaN even for an attribute that is the same at every vertex.
The near-plane pass then interpolates from that vertex, and the post-clip polygon is emitted as a fan from its first vertex, so every fan triangle carries a NaN vertex and the polygon's whole visible area reads NaN.
That is the case observed here, a large ground polygon under a low camera, but not the only one: the divisor is 0 for any edge whose endpoints share a screen x while their clip-space x differ, so the near plane alone can produce it, for example on the edge from (1, -1, -1, 2) to (2, 1, 1, 4) (screen x 0.5 at both ends and at the cut; review on #264).
The guard catches every non-finite `shade`, whichever edge produced it.
A GPU clips only near and far, with a guard band for x and y.
Evidence: (1) a temporary sentinel in `fragment_index` (NaN 250, infinity 251, out of range 252/253, more than 0.5 from `palette_index` 254) marked every layer-3 sample in rows 120-184 at CTRY 422 (10,134) and 400 (9,791) as NaN, and none at 1257.
(2) A float32 port of `do_clip_tri`/`interp` run on the 2,203 world-prop triangles within 1,500 m of the eye, with the tick's dumped `view_proj`: 184 need clipping and 62 of them cross the near plane, yet exactly one gives NaN.
That one is the index-196 triangle of the 128 m field tile under the eye (x 3200-3328, z 2432-2560).
Its first NaN comes where an edge on x = w (both endpoints at screen x 1.0) is cut by the opposite x plane at w = 0, and its clipped quad has 2 NaN vertices.
The other 61 near-crossing triangles stay finite, so the near-plane clip alone is not the cause in this frame.
Related upstream history: Mesa bug 98851 (2016, `noperspective` attributes wrongly interpolated after clipping) concerns the same `t_nopersp` code; no report of this zero divisor was found.

The same fault shows on both mesa-dist-win builds, and upstream has not changed the code (`[Bounded Observation]`, 2026-11-15, `crates` `52d84e6`).
With the guard removed, CTRY 400 draws 41,933 index-0 pixels on 25.2.8 and 41,934 on 26.2.6 (none on the GPU), and LOCATION 3994 44,580 and 44,427.
A sentinel build (non-finite `shade` 250, below -0.5 251, above 255.5 252) draws 250 on those pixels, all but the at most five per tick that differ from the GPU with the guard on too, and draws no 251 or 252, on either build, at CTRY 400 and 422 and LOCATION 3994, 4005, 4445 and 4467.
Which polygons it hits moves with the build: at CTRY 422 it draws index 0 on 43,117 pixels on 25.2.8 and 410 on 26.2.6, at LOCATION 4467 on 41,057 and 100.
`interp()` reads the same in `mesa-26.2.6` as in `mesa-25.2.8`; the one difference in `draw_pipe_clip.c` between the two tags is a `SWAP` macro in `do_clip_tri` (`8a1a4103`, 2025-07-23), which is also the file's last commit on `main` as read on 2026-11-15.
_Source: [Lavapipe beside the GPU on one crates tree](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

A standalone Vulkan repro with no Stunt Reel code shows both mechanisms (`[Bounded Observation]`, 2026-11-16): a `noperspective` varying that is 1.0 at every vertex reads NaN on every covered pixel on mesa-dist-win 25.2.8 and 26.2.6 (1,077 pixels for an edge left on x = w and cut at w = 0, 442 for an edge of constant screen x that only the near plane cuts), and 1.0 on the RTX 4070; its upstream issue is drafted, not filed.
_Source: [the repro, its replay and the issue draft](../../work/2026-11/lavapipe-clip-nan/README.md)._ It reads the same on a Linux package, Ubuntu 26.04.1's `mesa-vulkan-drivers` 26.0.8-1ubuntu0.3 (`llvmpipe (LLVM 21.1.8, 256 bits)`) under WSL 2: 1,077 and 442 NaN pixels and no NaN in the control (`[Bounded Observation]`, 2026-11-16, `3a7afb76`). _Source: [the repro on Ubuntu 26.04's Mesa 26.0.8](../../work/2026-11/642_wsl-clip-nan/journal.md#2026-11-16-the-repro-on-ubuntu-2604s-mesa-2608-and-why-no-patched-mesa-build)._
The draft's suggested `interp()` change (choose the axis by the screen-space difference, and keep the 3D `t` when no axis gives a finite weight) stops it on this repro (`[Bounded Observation]`, 2026-11-18, `91ad1d3`): lavapipe built from `mesa-25.2.8` with LLVM 20.1.2 drew 1,077 and 442 NaN pixels unpatched, as Ubuntu 24.04's package did, and 1.0 on every covered pixel with the change; the repro's varying is the same at every vertex, so values of one that varies were not checked.
_Source: [stock and patched lavapipe builds](../../work/2026-11/702_mesa-interp-fix-build/journal.md#2026-11-18-stock-and-patched-lavapipe-builds-of-mesa-2528)._

## 3. The fix: a guard, then the screen-linear ratio

`[Bounded Observation]` on lavapipe (the guard on Ubuntu's Mesa 25.2.8, (d) and (e) on mesa-dist-win 25.2.8) and the RTX 4070, each step as dated in its source.
`vs_main` outputs `shade * w` and `w` beside `shade`, where `w` is the final `clip_position.w` after `widen_line`, both `@interpolate(perspective)`.
`fragment_index` rounds `@interpolate(linear) shade`; where that is not finite (exponent bits all set) it rounds `shade_w / w`, and falls back to the flat `palette_index` only when that ratio is not finite either.
It came in three steps, each adopted on top of the last: the guard to `palette_index` (candidate (c), 2026-11-07), a `perspective` copy of `shade` (candidate (d), #595), and the ratio in place of that copy (candidate (e), #635).
_Source: [Candidate fixes for the NaN shade](../../work/2026-11/distill-lavapipe/journal.md#2026-11-07-candidate-fixes-for-the-nan-shade), [A perspective copy of the shade](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-a-perspective-copy-of-the-shade), [The screen-linear ratio at BALLOON 145](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-the-screen-linear-ratio-at-balloon-145-before-and-after)._

* **What the guard did.**
  On `b0c90c2` and `9f04164` (identical renderer), lavapipe's `mean_ssim_scored` for CTRY / INTRO went from 0.6446 / 0.6040 to 0.8722 / 0.8281 and index agreement from 0.663 / 0.612 to 0.8893 / 0.8289, IoU 0.9897 / 0.9856 throughout.
  On lavapipe it drew a Gouraud polygon the clipper broke in its provoking vertex's index instead of its gradient (BALLOON 145, section 5).
  _Source: [Candidate fixes for the NaN shade](../../work/2026-11/distill-lavapipe/journal.md#2026-11-07-candidate-fixes-for-the-nan-shade)._
* **Why the ratio.**
  `interp()` gives a perspective attribute the 3D weight `t` (section 2), so a Gouraud polygon the clipper breaks keeps a gradient.
  The perspective-correct interpolation of `a·w` divided by that of `w` is the screen-space linear interpolation of `a`, the same screen-space-linear rule as the GPU's `linear` varying and PLAYONE's filler ([`terrain-shade.md`](../playone-exe/terrain-shade.md) section 6, which interpolates in 8.8 fixed point, not f32); (d)'s copy was the perspective interpolation of `a`, which differs from it wherever `w` varies across the polygon.
  It is exact at a vertex the clipper makes (`[Supported Inference]`, from the `interp()` reading of section 2, not measured at the vertex): `interp()` gives a perspective attribute the finite 3D weight `t`, so at a cut along an edge the two varyings are `(1-t)·a0·w0 + t·a1·w1` and `(1-t)·w0 + t·w1`, whose ratio is the screen-space lerp of `a` at that point, and `w` is positive after the near-plane clip.
  The ratio is computed in f32, so a pixel whose value sits on a `.5` rounding boundary can still round either way against the GPU's; all 4,044 of BALLOON 145's pixels round as the GPU's, which does not show that none sat on a boundary.
  _Source: [The screen-linear ratio at BALLOON 145](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-the-screen-linear-ratio-at-balloon-145-before-and-after)._
* **What it costs.**
  Shader-only.
  The guard leaves the RTX 4070's index planes byte-identical (section 4).
  With (d), and again with (e), the RTX 4070's `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical to `origin/main`'s over every reference film's captured ticks, (e) last against `e6fb29ce`'s after #650's eye-relative transforms (21 of 21 files), because a GPU's `linear` varying is finite and the fallback is not read on the captured ticks.
  Lavapipe's `mean_ssim_scored` and `mean_iou_scored` are the same with and without (d), and with and without (e) (to the tables' seven decimals, `ba40ea63` against `3a7afb76`), on all seven films: BALLOON 145, where they act, is rendered but not scored.
  _Source: [A perspective copy of the shade](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-a-perspective-copy-of-the-shade), [The screen-linear ratio at BALLOON 145](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-the-screen-linear-ratio-at-balloon-145-before-and-after)._
* **Tests.**
  The GPU test `a_ground_polygon_under_a_low_eye_keeps_its_index` fails on lavapipe without the guard (section 1), and `a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient` draws a single index on lavapipe without (d)'s fallback.
  _Source: [A perspective copy of the shade](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-a-perspective-copy-of-the-shade)._

## 4. Lavapipe beside the GPU on one `crates` tree

`[Bounded Observation]`, 2026-11-15, all seven reference films, `crates` tree `52d84e6` (the `--software-only` branch, whose index planes on the GPU match `origin/main`'s tree `e1f9af7` on every tick), RTX 4070 laptop and mesa-dist-win 25.2.8 on the same machine; the cloud rows are #455's `expected.lavapipe` in [`references.toml`](references.toml), on `e1f9af7`.

**The guard leaves the RTX 4070's index planes byte-identical (20,621 ticks).**
With the guard removed, the GPU renders every tick of all seven films with the same index plane (sha256 of each 64,000-byte plane: 0 of 20,621 ticks differ).
A sentinel build draws no non-finite, negative or over-255 `shade` on the GPU at the eleven ticks of sections 2 and 5.

**Lavapipe rows match the GPU rows on all seven films**, within the 0.002 adoption margin, which is a policy bound and not a noise model ([`evidence-limits.md`](evidence-limits.md) section 3).
`mean_ssim_scored`, local lavapipe minus GPU: CTRY +0.0000212, INTRO -0.0004507, LAND +0.0004120, BALLOON -0.0006492, TRAINTNL -0.0002315, BOMB +0.0000422, LOCATION +0.0000457.
IoU agrees to 0.00002 or better on every film.

**Local and cloud lavapipe agree within 0.00004 but not identically**, on two LLVM versions and two `crates` trees: local minus cloud, CTRY +0.0000068, INTRO +0.0000006, LAND +0.0000001, BALLOON -0.0000370, TRAINTNL -0.0000002, BOMB +0.0000030, LOCATION +0.0000082; IoU within 0.00001.
No SSIM is identical at the tables' seven decimals.
By #265's criterion (every film within the 0.002 margin), rows from mesa-dist-win 25.2.8 matched the GPU rows on these seven films on this tree, and the cloud's Ubuntu 25.2.8 rows agree with them; this is not shown for CI's lavapipe or for 26.2.6, and a change to Gouraud polygons or to depth order can score differently on lavapipe (section 5).
That is a check on one tree; how far lavapipe and the GPU differ on later trees is the class agreement, which the agreement batch measures pixel by pixel and pins, with the same 0.002 bound on each film's SSIM gap ([ADR 0055](../../docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
Because the adapter names differ (LLVM 21.1.7 against 20.1.2), `mise run parity` reports a local run against those rows as `not comparable: other adapter`, so local renders are not drift-checked against them.
The owner decided on 2026-11-16 that local runs do not repin the `lavapipe` class: `mise run parity-repin -- --class lavapipe` here regenerates `expected/lavapipe.toml` from a local run and swaps every film's adapter to LLVM 21.1.7, after which cloud and CI runs read `not comparable: other adapter` and lose their drift check; #649 measures how far builds differ pixel by pixel.
_Source: [Lavapipe beside the GPU on one crates tree](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

## 5. What still differs

Near-cut outline lines, which lavapipe drew as wedges until the line lists were clipped to a band around the view (#922), are in [`lavapipe-line-clip.md`](lavapipe-line-clip.md).

`[Bounded Observation]`, 2026-11-16, mesa-dist-win 25.2.8 against the RTX 4070, on `origin/main` `3a7afb76` with (d) but not (e).
With eye-relative transforms (#636), lavapipe differs from the GPU by 12.31 to 62.85 index-plane pixels per tick on average over each film, against 22.64 to 147.44 on the same tree without them (table below); (e) and #636 together were not measured on lavapipe.
_Source: [Eye-relative transforms on both backends](../../work/2026-11/636_eye-relative-transforms/journal.md#2026-11-16-eye-relative-transforms-on-both-backends)._

**Reversed, infinite depth (#637).**
`[Bounded Observation]`, 2026-11-20, mesa-dist-win 25.2.8 against the RTX 4070, on `main` `5fbfe844` before and that tree plus the change after; re-measured on `main` `b028f7d3` (#690) with the same figures to one decimal.
Depth was then `0.5 m / w` (`0.1 m / w` since [#904](https://github.com/neilsh/stunt-reel/issues/904), not re-measured here), reversed, in `Depth24Plus` ([ADR 0054](../../docs/adr/0054-depth-is-reversed-and-infinite.md)): clip z is the constant near distance, so no rounded projection term reaches it.
Mean index-plane pixels differing per tick, GPU against lavapipe, over every tick of each film, with the same projection in `Depth32Float` beside it:

| Film | Before | `Depth32Float` | After (`Depth24Plus`) |
|---|---|---|---|
| CTRY | 12.2 | 12.0 | 6.3 |
| INTRO | 12.8 | 12.1 | 8.9 |
| LAND | 35.7 | 46.5 | 26.2 |
| BALLOON | 19.9 | 44.6 | 8.9 |
| TRAINTNL | 20.7 | 30.9 | 5.2 |
| BOMB | 14.7 | 26.6 | 11.6 |
| LOCATION | 62.0 | 92.7 | 29.8 |

The largest ties left move less: LOCATION 3815 3,131 to 1,490 pixels and 3830 2,603 to 2,470; LAND 415 1,867 to 1,858 and 416 2,096 to 2,075, so the change barely moves LAND's terrain-against-prop tie; 145 of the 152 pixels #904 left at LAND 416 (on mesa-dist-win) went with the outline clip band, so those 145 were outline lines reaching outside it, not a tie, and the other 7 are not attributed ([`lavapipe-line-clip.md`](lavapipe-line-clip.md) section 2).
At LOCATION 3815, 3824, 3828 and 3830 on `main` `b9441a06`, nearly all of the pixels the canonical lavapipe and the RTX 4070 drew differently (325 of 335, 572 of 584, 490 of 513, 560 of 575) were the castle's green strip (index 136) on one against its moat (193) on the other: two flat props 75 m up, in one plane, whose order the depth compare settled.
Since #966 the strip is drawn as a decal of the moat, as `PLAYONE` paints it; those ticks differ by 11, 12, 23 and 15 pixels, none of them that pair, and LOCATION 3812 to 3968 by 12.64 a tick against 132.08, its worst tick 39 against 584 ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.9).
_Source: [A flat prop lying on an earlier flat prop is a decal of it](../../work/2026-11/966_moat-walk-order/journal.md#2026-11-22-a-flat-prop-lying-on-an-earlier-flat-prop-is-a-decal-of-it)._
In `Depth32Float`, on the four films tallied (BALLOON, BOMB, LAND, TRAINTNL), most of the extra pixels were lavapipe's own plane moving, between polygons of one layer (on BALLOON the balloon's actor layer, 14.8 to 40.1 pixels per tick), and at 13 sampled ticks no decal bias constant from 0 to 1,024 or slope from 2 to 8 changed that by more than 7 pixels a tick.
`[Supported Inference]`: rounding the interpolated depth to a 24-bit step absorbs the small differences between the two rasterizers' depth interpolation that f32 keeps, so coplanar ties resolve by the compare function alike on both.
GPU parity moves inside every guard (no film down by 0.002, no frame by 0.005).
`[Bounded Observation]`, 2026-11-22, the canonical lavapipe (Ubuntu `mesa-vulkan-drivers` 25.2.8 under WSL 2) against the RTX 4070, on `main` `44a3bf31` (0.1 m near plane, outline clip band) and that tree with `Depth32Float`: the mean per tick rose on every film, CTRY 3.09 to 9.55, INTRO 2.22 to 5.73, LAND 5.23 to 27.36, BALLOON 4.12 to 46.23, TRAINTNL 3.66 to 29.16, BOMB 8.40 to 27.62, LOCATION 8.59 to 80.23, and LOCATION's ticks over 500 pixels from 3 to 156.
_Source: [Depth32Float again](../../work/2026-11/637_reversed-z/journal.md#2026-11-22-depth32float-again-after-the-01-m-near-plane-and-the-outline-clip-band); [Reversed depth in Depth24Plus over every tick](../../work/2026-11/637_reversed-z/journal.md#2026-11-20-reversed-depth-in-depth24plus-over-every-tick-both-backends); [on main after #690](../../work/2026-11/637_reversed-z/journal.md#2026-11-20-the-committed-code-on-main-after-690-both-backends); [in Depth32Float](../../work/2026-11/637_reversed-z/journal.md#2026-11-20-reversed-depth-in-depth32float-over-every-tick-both-backends); [bias or format at 13 ticks](../../work/2026-11/637_reversed-z/journal.md#2026-11-20-bias-or-format-at-13-ticks)._

**Eye-relative transforms (#636).**
`[Bounded Observation]`, 2026-11-16, mesa-dist-win 25.2.8 against the RTX 4070, on `origin/main` `3a7afb76` before and that tree plus the change after.
Each draw's matrix is now `translate(-eye) * model`, rounded to f32 once on the CPU, and the camera uniform carries the view's rotation and projection only (`camera.rs` `eye_relative_matrix`), so the only world-scale arithmetic left in the vertex stage is a world vertex's `position - eye`, which its identity rotation rounds once in any evaluation order.
Mean index-plane pixels differing per tick, GPU against lavapipe, over every tick of each film:

| Film | Ticks | Before | After |
|---|---|---|---|
| CTRY | 1,320 | 22.64 | 12.31 |
| INTRO | 3,807 | 29.33 | 14.19 |
| LAND | 1,123 | 119.24 | 42.43 |
| BALLOON | 1,179 | 40.97 | 18.58 |
| TRAINTNL | 1,222 | 62.46 | 21.22 |
| BOMB | 3,719 | 98.61 | 15.81 |
| LOCATION | 8,251 | 147.44 | 62.85 |

The four near-coplanar ties below go (all differing pixels per tick, before and after): LAND 227 3,290 to 17, BOMB 1910 583 to 1, LOCATION 2599 5,638 to 14 and 2859 5,736 to 5.
The before column's BALLOON figure is lower than the 43.5 measured on `52d84e6`, presumably because #595's perspective copy came between the two trees (not measured); the other six match `52d84e6`'s.
The largest per-tick differences left are not those ties: LOCATION 3815 (3,130 pixels, 3,088 of them index 193 on the GPU against 136 on lavapipe, both in the prop layer; before, 2,701, the same two indices the other way round), LAND 415 (2,084, 1,854 of them the GPU's terrain at 195 against lavapipe's prop at 13, the same pair on as many pixels as before) and BALLOON 145 (1,091, the Gouraud polygon one index off, candidate (d); candidate (e) was measured on `3a7afb76`, before this change, and the two together were not measured on lavapipe).

The change moves the GPU's own render: where the stadium's infield (a world prop, index 169) lies over the plaza prop `0x064A` (index 14) at LOCATION 2586 to 2872, the GPU before drew the infield over most of the stadium with the ground breaking through on its far side, and now draws the ground over nearly all of it at the ticks #636 measured (2586, 2599, 2840, 2859, 2862), as lavapipe did before at 2586, 2840 and 2859 (at 2599 the GPU drew the ground before too, and lavapipe the infield); the capture shows the whole infield, as PLAYONE paints it.
The plaza, snapped onto the ground plane, is drawn by the ground pipeline, which writes depth, and the infield, a base polygon 7.8125 mm below it in our world IR, must pass `Less` (standard depth) against it, so an exact depth test draws the plaza ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.8; #651).
Since 2026-11-20 the ground pass takes the infield too and paints it over the plaza, as the capture shows (measured on the GPU; same section).
The infield won before #636 by the f32 vertex-stage error, not by depth precision (`[Supported Inference]`: a 7.8125 mm offset seen from about 85 m (near plane 0.5 m) is a depth gap of at most `0.5 / 85² × 0.0078125 = 5.4e-7`, while #595 read 3.2e-6 and 2.9e-6, of opposite sign, near depth 0.994; so the f32 vertex-stage error that #636 removed flipped it, not depth precision).
Those frames fall by up to 0.053 in SSIM, and LOCATION's mean by 0.0005 (scores in the journal entry).
Of the 24 frames on the seven films that fall by more than 0.005, 14 are this tie, 3 the LOCATION 3815 prop tie, 3 a prop against the terrain at LOCATION 5710 to 5809, on which the two backends now differ by 1 to 5 pixels, and 4 are small scattered changes (LOCATION 3719 and 4236, BOMB 2113 and 3433) not attributed further.
_Source: [Eye-relative transforms on both backends](../../work/2026-11/636_eye-relative-transforms/journal.md#2026-11-16-eye-relative-transforms-on-both-backends)._

* **A Gouraud polygon the clipper breaks** (BALLOON 145; `[Bounded Observation]`, 2026-11-16, `3a7afb76`, with (e) on `ba40ea63`): a local sentinel build marks 4,044 clipper-broken pixels of a Gouraud (`GVPOLY`) polygon on lavapipe, where the GPU draws a 169-171 gradient (170 on 3,784, 169 on 147, 171 on 113).
  The guard alone drew a flat 168; (d) drew 1,090 of the 4,044 one index below the GPU; (e) draws all 4,044 as the GPU does, and the frame's differing pixels fall from 1,097 to 7.
  Before against after (e), the lavapipe stores (`mise run parity-residue`) differ only on BALLOON: 1,090 pixels at tick 145, all inside the 4,044, and 2 at tick 143 (lavapipe's 49 becomes the GPU's 50, not traced to a broken polygon); BALLOON's mean falls from 41.0 to 40.0, and `mise run judge --track evidence` moves no scored frame on either backend.
  _Source: [The screen-linear ratio at BALLOON 145](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-the-screen-linear-ratio-at-balloon-145-before-and-after)._
* **A near-coplanar polygon won the depth test** before #636, which cuts each to 17 pixels or fewer (LAND 227, BOMB 1910, LOCATION 2599 and 2859; `[Bounded Observation]`, 2026-11-16, `03356d6e` with an uncommitted diagnostic writing each fragment's pipeline, provoking `vertex_index` and depth).
  The two backends drew different polygons there: at each residue pixel where both were read alone (all but 16 of LAND's 3,222), the GPU put the polygon it shows in front by 6e-8 to 4.5e-4, and lavapipe put it level or behind.
  Three are ground against a world prop, where the ground pipeline compares `Always` and writes depth, so the prop's `Less` test (standard depth) decides; at BOMB 1910 an actor's decal fails `LessEqual` against its own base polygon on lavapipe.
  The clipper broke the ground polygons at LAND 227 and LOCATION 2859 (inferred from the NaN, by section 2's mechanism: `shade` reads non-finite on 2,686 of LAND's 3,222 pixels and on LOCATION 2859's ground), and LAND 227's is flat in effect, so it is not a Gouraud polygon drawn flat.
  _Source: [Which polygon each backend draws](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks)._

The vertex stage already differed (`[Supported Inference]`, on `03356d6e`, before #636 changed the transform): by its provoking vertex's clip-space z bits, z differs in 133 of 306 polygons both backends draw at LAND 227 (by up to 2,048 ulp), 89 of 313 at BOMB 1910 (16,384 ulp) and 67 of 231 at LOCATION 2859 (128 ulp), and polygons whose pixels stay off the viewport's edge differ in depth too (a median of 986 D24 units at LAND 227, 67 to 74 at LOCATION), so clipping is not the only source of the depth differences.
The samples are small (7 to 16 polygons reaching the edge per tick), and at BOMB 1910 the polygons reaching the edge differ more (median 1,034 over 10, against 33 over 2 off it); whether the clipper adds to a broken polygon's depth error is not separated, and why the two compilers round the transform differently is not shown.
Both backends take `X8_D24_UNORM_PACK32` for `Depth24Plus`.
_Source: [The vertex stage at the four residue ticks](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-the-vertex-stage-at-the-four-residue-ticks)._

* **The hero's shadow at CTRY 422 is solid** (`[Bounded Observation]`, 2026-11-15, `crates` `52d84e6`) on the GPU, 25.2.8 and 26.2.6 alike (1,342, 1,343 and 1,346 index-0 pixels in actor layer 16; the lavapipe frames differ from the GPU's by 25 and 23 pixels in all).
  The patches of the 2026-11-07 picture on `72028d1` do not recur on this tree; which of the 53 `crates/` commits since removed them is not bisected (#495, the ordered decal pass with depth bias, is one candidate).
  _Source: [Lavapipe beside the GPU on one crates tree](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

A near-zero but finite divisor would give a Gouraud polygon a wrong but finite weight that the guard cannot catch; the sentinel found no `shade` below -0.5 or above 255.5 on lavapipe at any tick rendered, and no case is known.
_Source: [Lavapipe beside the GPU on one crates tree](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

## 6. One build on two machines

`[Bounded Observation]`, 2026-11-21, `crates` tree `9d08971`, all seven reference films, every tick.
Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`) drew the same index plane on every one of the 20,621 ticks on an AMD Ryzen 7 7745HX under WSL 2 as on a Claude cloud container's Intel Xeon (compared by per-tick SHA-256, the sorted tick hashes hashed again per film and per 200 ticks), so on this tree one pinned package gave local-windows and the cloud the same pixels.
mesa-dist-win 25.2.8 (`LLVM 21.1.7`) on the Ryzen differs from it on 5 to 201 ticks per film, by at most 33 pixels on a tick (BALLOON 1084) and at most 0.3 pixels per tick on average; it and the Ubuntu package each repeat their own planes exactly on a second run.
Against the RTX 4070 on that machine both differ by the same per-tick means to one decimal (CTRY 6.3, INTRO 8.9, LAND 26.2, BALLOON 8.9, TRAINTNL 5.2, BOMB 11.6, LOCATION 29.8), matching section 5's reversed-depth column; both were measured with the 0.5 m near plane, which #905 has since moved to 0.1 m.
Their `mean_ssim_scored` lies within 0.0005 of the GPU's on every film, and within 0.000003 of each other.
Seven films took 1 m 43 s on mesa-dist-win and 2 m 34 s to 2 m 37 s on the Ubuntu package under WSL on the Ryzen (49.8 s on the GPU), and 251 s on the cloud's 4 vCPUs; under WSL the data root must lie on the Linux filesystem (CTRY 4.4 s there, 36 s read from `/mnt/e`).
Ubuntu's archive does not keep every version: `25.2.8-0ubuntu0.24.04.4`, which section 2 names, is gone, and a fresh 24.04.5 install came with `.2`, so an exact pin fails at install once Ubuntu supersedes it.
_Source: [Four renderer builds on one crates tree, two machines](../../work/2026-11/908_backend-agreement/journal.md#2026-11-21-four-renderer-builds-on-one-crates-tree-two-machines)._

## Ruled out

* **The actor shadow draw** (CTRY 422): with it off, the ground stays black.
* **The decal depth bias** (CTRY 422): with slope 0, the ground stays black.
* **Crossing the near plane as the cause in this frame**: 61 of 62 near-crossing triangles at CTRY 422 stay finite (section 2), though an edge of constant screen x can produce the NaN at the near plane alone.
* **`shade` `@interpolate(perspective)` everywhere (candidate (a))**: on lavapipe it scores as the guard does on CTRY and INTRO, but on a GPU a Gouraud (`GVPOLY`) polygon's index becomes perspective-correct instead of screen-linear, which departs from PLAYONE's filler, and its lavapipe stores differ from the guard's; [journal](../../work/2026-11/distill-lavapipe/journal.md#2026-11-07-candidate-fixes-for-the-nan-shade).
* **A flat `palette_index` unless the polygon is Gouraud (candidate (b))**: it needs a `SodVertex` flag (a seam-contract change), and Gouraud polygons stay exposed on lavapipe; with the guard it is byte-identical to the guard alone on lavapipe on CTRY and INTRO; [journal](../../work/2026-11/distill-lavapipe/journal.md#2026-11-07-candidate-fixes-for-the-nan-shade).
* **A flat `palette_index` everywhere** (a diagnostic): it drops `GVPOLY` interpolation (CTRY / INTRO 0.8721 / 0.8231 on lavapipe); [journal](../../work/2026-11/distill-lavapipe/journal.md#2026-11-07-candidate-fixes-for-the-nan-shade).
* **A `perspective` copy of `shade` for the clipper's polygons (candidate (d))**: its gradient was one index off the GPU's screen-linear one on 1,090 of BALLOON 145's 4,044 broken pixels; the ratio (e) replaced it; [journal](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-a-perspective-copy-of-the-shade).
* **A renderer change, #249's adapter choice included, as the cause of the lavapipe loss**: guarding the one NaN value leaves lavapipe less than the 0.002 adoption margin from the GPU at the same renderer ([`evidence-limits.md`](evidence-limits.md) section 3), too little for a renderer change to hide a 0.23 loss behind.
* **A LOCATION fault the guard misses** (mesa-dist-win 25.2.8): a first local LOCATION run scored 0.6344817 because its binary was a guard-removed build reused with `--no-build`, and rendered again with the guard it scores 0.8292054 (index agreement 0.8405, as the GPU's); [journal](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-a-first-local-location-run-on-a-guard-removed-binary).
* **A finite out-of-range `shade` on lavapipe, at the ticks rendered**: the sentinel drew no `shade` below -0.5 or above 255.5 at CTRY 400 and 422, LOCATION 3994, 4005, 4445 and 4467, BALLOON 145, LAND 227, BOMB 1910 or LOCATION 2599 and 2859, on 25.2.8, nor at the first six on 26.2.6 (section 5); [journal](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree).
* **The GPU polygon's shade at BOMB 1910 and LOCATION 2599 and 2859**: all-flat polygons still differ there (section 5); [journal](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree).
* **LAND 227 as a Gouraud polygon drawn flat**: lavapipe draws a flat ground polygon over the GPU's prop there (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **A different depth format on the two backends**: both take `X8_D24_UNORM_PACK32` for `Depth24Plus` (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **The clipper as the sole cause of the depth residues** (mesa-dist-win 25.2.8): polygons the side planes do not clip differ in depth too, and provoking vertices differ out of the vertex stage (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **Reversed, infinite depth in `Depth32Float`** (#637's proposal; mesa-dist-win 25.2.8): it raised the GPU-lavapipe residue on five of seven films, and the decal bias did not explain it; re-measured on the canonical lavapipe after #904 and #922, it raised it on all seven (section 5); [journal](../../work/2026-11/637_reversed-z/journal.md#2026-11-20-reversed-depth-in-depth32float-over-every-tick-both-backends).
* **An upstream fix by Mesa 26.2.6**: its clipper still makes the NaN, and `interp()` is unchanged through `main` (section 2); [journal](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree).
* **Unpacking the canonical Ubuntu lavapipe on cloud-antigravity's Debian 12** (#806): `libvulkan_lvp.so` in `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` and `libLLVM.so.20.1` in `libllvm20` `1:20.1.2-0ubuntu1~24.04.3` import `GLIBC_2.38` symbols (`__isoc23_strtol`, `__isoc23_strtoul`, `__isoc23_strtoll`, `__isoc23_strtoull` and `__isoc23_sscanf`, plus `__isoc23_scanf`, `fmod` and `fmodf` in `libLLVM.so.20.1`), and `libLLVM` asks for `GLIBCXX_3.4.32`; Debian 12 has glibc 2.36, below that, and its GCC 12 libstdc++ provides up to `GLIBCXX_3.4.30`, below `libLLVM`'s request; the Vulkan loader loads the driver into the renderer's process, so it cannot load; running the renderer under a separate, newer glibc was not tried; [journal](../../work/2026-11/806_antigravity-lavapipe/journal.md#2026-11-23-the-canonical-ubuntu-lavapipe-cannot-load-on-debian-12).

## Open questions

1. Narrowed by #636 (section 5): taking the eye's translation out of the f32 transform removes the ties at the four residue ticks (17 pixels or fewer left at each) and cuts the per-tick difference by 46% to 84%, so the cancellation drove them; the mechanism inside each compiler is not shown.
   Still open: which compiler step rounds the transform differently (fused multiply-adds in one compiler and not the other is one candidate), and whether the ties that remain (LAND 415; 145 of LAND 416's 152 remaining pixels went with the outline clip band and its last 7 are not attributed, [`lavapipe-line-clip.md`](lavapipe-line-clip.md)) are polygons in one plane: reversed depth (#637, section 5) removed under 6% of LAND 415's and 416's differing pixels (1,867 to 1,858, 2,096 to 2,075), but against `main` it changed the projection (clip z the constant `near`), the compare directions, the bias sign and where the 24-bit depth steps fall in distance together, in the same `Depth24Plus` format, so it does not show how much of each tie the projection's rounding makes; the stadium's infield at LOCATION 2586 to 2872 was neither: it lay 7.8125 mm below the plaza it tied, and the ground pass now paints it in walk order ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.8).
2. Whether a broken polygon's depth moves more than the vertex-stage difference explains (LOCATION 2859, section 5).
   Not filed upstream either: a report to Mesa would cite `t_nopersp`'s zero divisor (section 2).
3. Whether Mesa 26.2.6 scores as 25.2.8 does: it was rendered at six ticks only, with no parity run; and whether CI's runners draw section 6's planes, which two CPUs of different vendors did.
4. Whether replacing `@interpolate(linear) shade` everywhere with the ratio `shade·w / w` (so no render relies on Mesa's `noperspective` path) flips GPU pixels at `.5` rounding boundaries: #635 proposed counting the differing index-plane pixels against `main` over the seven films and did not run it (it was the issue's optional experiment; section 3 (e) adopts the ratio only where `shade` is not finite).
