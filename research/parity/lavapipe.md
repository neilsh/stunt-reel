---
summary: "Mesa's clipper can make the shade varying NaN; with the guard, local lavapipe scores within 0.002 of the GPU on all seven films. Eye-relative transforms, which take the eye's translation off each draw's matrix on the CPU, cut the per-tick difference by 46% to 84% on each film and shrink the four near-coplanar depth-tie residues to 17 pixels or fewer each; other ties remain. The screen-linear ratio `shade·w / w` makes the Gouraud polygons the clipper breaks draw the GPU's gradient (BALLOON 145 on `3a7afb76`: all 4,044 broken pixels match the GPU, 1,097 differing pixels in the frame become 7). One matrix upload per frame nearly halved its LOCATION render time, and keeping two frames in flight cut it further with the stores still identical over the seven films' captured ticks on the GPU and LOCATION ticks 12-300 on lavapipe. A LOCATION frame encodes 127,910 `draw_indexed` calls, nearly three quarters of them world base fills and outlines, none of which coalescing contiguous base slices in walk order removes on LOCATION; culling world nodes outside the view frustum cuts the median frame to 6,791 calls and LOCATION ticks 12-300's lavapipe render time by 83% (one run), with the stores byte-identical over every film's captured ticks."
---
# Parity: Rendering on Lavapipe

* **Scope**: how Mesa's software Vulkan driver, lavapipe, renders our frames differently from a GPU, and what the renderer does about it, and how long a lavapipe render takes.
  Cloud sessions ([ADR 0039](../../docs/adr/0039-cloud-sessions-fetch-pinned-game-archives.md)) and CI ([ADR 0006](../../docs/adr/0006-ci-renders-on-lavapipe.md)) both render on it.
  The findings name the Mesa build they come from; three builds were measured: Ubuntu's `mesa-vulkan-drivers` 25.2.8 (`llvmpipe (LLVM 20.1.2, 256 bits)`, cloud), and mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and 26.2.6 (`llvmpipe (LLVM 23.1.4, 256 bits)`) on the RTX 4070 laptop, set up by [`render-on-lavapipe.md`](../../docs/howto/render-on-lavapipe.md).
* **Sources**: Mesa source (`src/gallium/auxiliary/draw/draw_pipe_clip.c` at `mesa-25.2.8`, `mesa-26.2.6` and `main`; `src/gallium/drivers/llvmpipe/lp_context.c`), `cdb` stack samples and timed renders from #596, parity runs logged in [`log.md`](../../work/2026-10/parity-log/log.md) on 2026-11-07 and 2026-11-15, the #265 journal, and #635's parity and residue runs of 2026-11-16.
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
_Source: [the repro, its replay and the issue draft](../../work/2026-11/lavapipe-clip-nan/README.md)._ It reads the same on a Linux package, Ubuntu 26.04.1's `mesa-vulkan-drivers` 26.0.8-1ubuntu0.3 (`llvmpipe (LLVM 21.1.8, 256 bits)`) under WSL 2: 1,077 and 442 NaN pixels and no NaN in the control (`[Bounded Observation]`, 2026-11-16, `3a7afb76`). A Mesa build with the suggested `interp()` fix was not tried. _Source: [the repro on Ubuntu 26.04's Mesa 26.0.8](../../work/2026-11/642_wsl-clip-nan/journal.md#2026-11-16-the-repro-on-ubuntu-2604s-mesa-2608-and-why-no-patched-mesa-build)._

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
By #265's criterion (every film within the 0.002 margin), rows from mesa-dist-win 25.2.8 stand in for GPU rows on these seven films on this tree, and the cloud's Ubuntu 25.2.8 rows agree with them; this is not shown for CI's lavapipe or for 26.2.6, and a change to Gouraud polygons or to depth order can score differently on lavapipe (section 5).
Because the adapter names differ (LLVM 21.1.7 against 20.1.2), `mise run parity` reports a local run against those rows as `not comparable: other adapter`, so local renders are not drift-checked against them.
The owner decided on 2026-11-16 that local runs do not repin the `lavapipe` class: `mise run parity-repin -- --class lavapipe` here rewrites all seven rows from a local run and swaps every row's adapter to LLVM 21.1.7, after which cloud and CI runs read `not comparable: other adapter` and lose their drift check; #649 measures how far builds differ pixel by pixel.
_Source: [Lavapipe beside the GPU on one crates tree](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

## 5. What still differs

`[Bounded Observation]`, 2026-11-16, mesa-dist-win 25.2.8 against the RTX 4070, on `origin/main` `3a7afb76` with (d) but not (e).
With eye-relative transforms (#636), lavapipe differs from the GPU by 12.31 to 62.85 index-plane pixels per tick on average over each film, against 22.64 to 147.44 on the same tree without them (table below); (e) and #636 together were not measured on lavapipe.
_Source: [Eye-relative transforms on both backends](../../work/2026-11/636_eye-relative-transforms/journal.md#2026-11-16-eye-relative-transforms-on-both-backends)._

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
The plaza, snapped onto the ground plane, is drawn by the ground pipeline, which writes depth, and the infield, a base polygon 7.8125 mm below it in our world IR, must pass `Less` against it, so an exact depth test draws the plaza ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.8; #651).
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
  Three are ground against a world prop, where the ground pipeline compares `Always` and writes depth, so the prop's `Less` test decides; at BOMB 1910 an actor's decal fails `LessEqual` against its own base polygon on lavapipe.
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

## 6. Render time

`[Bounded Observation]`, 2026-11-15 to 2026-11-16, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) and the RTX 4070 on the same laptop, LOCATION ticks 12-300, headless at 320×200.
Each change left the render stores (`frames.zst`, `layers.zst`, `palettes.zst`) byte-identical, on lavapipe over LOCATION ticks 12-300 and on the GPU over every reference film's captured ticks.
Each row's before is its own tree, so the rows do not chain (this machine took 88.7 s on lavapipe for `5844b4b8`, #602's before, against 81.8 s for `80a3ad5`, #596's after):

| Change | Lavapipe before, after | GPU before, after |
|---|---|---|
| One matrix upload per frame (#596, after on `80a3ad5`, one run each) | 150.5 s, 81.8 s | 20.9 s, 16.0 s |
| Two frames in flight (#602, `5844b4b8` before, two runs each) | 88.7 s and 89.9 s, 76.3 s and 78.2 s | 16.7 s and 16.6 s, 12.4 s and 12.6 s |
| Frustum cull (#644, `857f80a8` before, PR #652 at `3e956d1a` after, one run each) | 81.7 s, 13.7 s | 14.6 s, 4.7 s |

#596 also cut the GPU's full captures, LOCATION's (ticks 12-8262) from 301.2 s to 229.6 s and INTRO's (12-3818) from 96.8 s to 67.8 s.
_Source: [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame), [Two frames in flight](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-two-frames-in-flight), [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum)._

**One matrix upload per frame (#596).**
`SceneRenderer::prepare` wrote each draw's model matrix with its own `write_buffer`, and wgpu allocates a staging buffer per call; on lavapipe that allocation held about half of the main-thread samples, with the process at 1.00 core whatever `LP_NUM_THREADS` was (why it costs more there than on the NVIDIA driver is not measured). #596 packs a frame's matrices into one uniform buffer at dynamic offsets, uploaded with one `write_buffer`.
Afterwards 16 of 20 main-thread samples sit in `wait_for_fence`, inside `vulkan_lvp`, and none in staging allocation, and all-thread samples put lavapipe's work on the one `vulkan_lvp` thread that executes command buffers (busy in 52 of 65 all-thread samples), known by offset only since mesa-dist-win ships no PDBs ([#600](https://github.com/neilsh/stunt-reel/issues/600)); on the GPU only the main thread is busy, 8 of its 42 samples in `GpuModel::collect_world_meshes`.
_Source: [2026-11-15: where a frame's time goes after the change](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-where-a-frames-time-goes-after-the-change), [One model-matrix upload per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-15-one-model-matrix-upload-per-frame)._

**Two frames in flight (#602).**
The offscreen target waited for each frame's readback, so the main thread and lavapipe's command-buffer thread did not overlap.
The headless loop now submits tick N+1 before it maps tick N's readback buffers, and waits only for tick N's own submission; pages still reach the sink in tick order.
The seven `mise run parity` score lines do not move.
_Source: [Two frames in flight in headless capture](../../work/2026-11/602_headless-capture-two-frames/journal.md#2026-11-15-two-frames-in-flight-in-headless-capture)._

**Draws per frame (#603, #644).**
Before the cull, the median LOCATION frame (ticks 12-300, `b0f6c120`, the same 289 per-frame counts on both backends) encoded 127,910 `draw_indexed` calls: 8,963 world ground fills and 6,269 ground outlines, 49,257 world base fills and 45,560 base outlines (94,817, 74.1%), 5,550 world decal fills and 5,549 decal outlines, and 6,762 prop, actor and sprite fills.
The world uploads as one chunk of 6,702,496 vertices and 7,488,138 indices, so every base slice draws with base vertex 0 from its own index range, and the base walk emits a parent's child slices in the reverse of their index order; in none of the 289 frames did an adjacent pair of base slices continue the previous one's index range, so coalescing them removes no call (#603's decision: no-go against its 25% bar).
_Source: [Draws per frame](../../work/2026-11/distill-lavapipe/journal.md#2026-11-16-draws-per-frame)._

**Frustum cull (#644).**
`[Bounded Observation]`, 2026-11-16, PR #652 at `3e956d1a` against `857f80a8`, mesa-dist-win 25.2.8 and the RTX 4070 laptop, LOCATION ticks 12-300, one run each.
The world walk skips a node whose box around its own and its descendants' vertices lies wholly outside one plane of the view frustum.
Over #603's 289 frames the median frame's `draw_indexed` calls fall from 127,910 to 6,791: the six world categories' medians from 121,148 in sum to 29 (the world's per-frame total at most 133), as these frames look at an aircraft against sea and sky; the 6,762 prop, actor and sprite fills are not culled.

Render times are in the table above.
On top of #636's eye-relative transforms (`e6fb29c`), on `origin/main` `734d3a8`, Ubuntu's Mesa 25.2.8 rendered all seven films' captured ticks byte-identical with and without the cull, 2026-11-17; the GPU was not re-checked there.
`852db54`, which stops moving each box by the node's `local_matrix`, was not re-run; every world node's `local_matrix` is the identity (`stunt_core::world::mesh`), so no box changes.
_Source: [culling world nodes outside the view frustum](../../work/2026-11/644_frustum-cull/journal.md#2026-11-16-culling-world-nodes-outside-the-view-frustum), [the cull on top of eye-relative transforms](../../work/2026-11/644_frustum-cull/journal.md#2026-11-17-the-cull-on-top-of-eye-relative-transforms)._

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
* **LLVM shader compilation, or `LP_NUM_THREADS`, as the cost of a lavapipe render** (mesa-dist-win 25.2.8): `GALLIVM_PERF=nopt` (47.5 s against 48.4 s over LOCATION ticks 12-100) and 1, 4 or unset threads left the time and the frames unchanged; [journal](../../work/2026-11/596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame).
* **LAND 227 as a Gouraud polygon drawn flat**: lavapipe draws a flat ground polygon over the GPU's prop there (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **A different depth format on the two backends**: both take `X8_D24_UNORM_PACK32` for `Depth24Plus` (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **The clipper as the sole cause of the depth residues** (mesa-dist-win 25.2.8): polygons the side planes do not clip differ in depth too, and provoking vertices differ out of the vertex stage (section 5); [journal](../../work/2026-11/595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks).
* **An upstream fix by Mesa 26.2.6**: its clipper still makes the NaN, and `interp()` is unchanged through `main` (section 2); [journal](../../work/2026-11/265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree).
* **Coalescing contiguous world base slices as a speed-up** (LOCATION): no adjacent pair of the base list in walk order continues the previous one's index range, so it removes 0 of a frame's 127,910 `draw_indexed` calls on the 289 frames measured (section 6); [journal](../../work/2026-11/603_draw-counts-per-frame/journal.md#2026-11-16-draws-per-frame-and-coalescing-adjacent-base-slices).
* **A cloud session as the place to measure #629's relit-vertex rewrite cost** (Ubuntu's Mesa 25.2.8, 4 vCPUs): a whole INTRO render took 147.4 s and 129.5 s with the rewrite and 133.7 s without it, so mesa-dist-win's 11.4 s cost (one run each way, #474) is smaller than the spread between identical runs there, `[Bounded Observation]`; [journal](../../work/2026-11/629_relight-cost/journal.md#2026-11-18-the-rewrites-cost-on-the-clouds-lavapipe).

## Open questions

1. Narrowed by #636 (section 5): taking the eye's translation out of the f32 transform removes the ties at the four residue ticks (17 pixels or fewer left at each) and cuts the per-tick difference by 46% to 84%, so the cancellation drove them; the mechanism inside each compiler is not shown.
   Still open: which compiler step rounds the transform differently (fused multiply-adds in one compiler and not the other is one candidate), and whether the ties that remain (LOCATION 3815, LAND 415) are left to depth precision (#637) or are polygons in one plane; the stadium's infield at LOCATION 2586 to 2872 is not: it lies 7.8125 mm below the plaza it ties ([`world-scene-residuals.md`](../playone-exe/world-scene-residuals.md) section 6.8).
2. Whether a broken polygon's depth moves more than the vertex-stage difference explains (LOCATION 2859, section 5).
   Not filed upstream either: a report to Mesa would cite `t_nopersp`'s zero divisor (section 2).
3. Whether Mesa 26.2.6 scores as 25.2.8 does: it was rendered at six ticks only, with no parity run; and CI's lavapipe has not been compared with these rows.
4. Which lavapipe functions hold its command-buffer thread, busy in 52 of 65 samples of a 0.28 s LOCATION tick after #596, and whether fewer draws ([#603](https://github.com/neilsh/stunt-reel/issues/603)) shorten it (section 6, [#600](https://github.com/neilsh/stunt-reel/issues/600)); #602 overlapped the readback with the next tick's work, which section 6 measures.
5. Whether caching the world's visible mesh slices while the camera holds still is worth it now that readback overlaps the next tick (#602, section 6): `GpuModel::collect_world_meshes` depends only on the world, the eye, and the authored view's eye, target and lens, and took 8 of 42 GPU main-thread samples in #596's profile.
   The overlap took the GPU run from 16.7 s to 12.4 s, so what remains is the main-thread work plus the part of the wait the pipeline cannot hide; whether a cache shortens that enough to pay is unmeasured.
6. Whether replacing `@interpolate(linear) shade` everywhere with the ratio `shade·w / w` (so no render relies on Mesa's `noperspective` path) flips GPU pixels at `.5` rounding boundaries: #635 proposed counting the differing index-plane pixels against `main` over the seven films and did not run it (it was the issue's optional experiment; section 3 (e) adopts the ratio only where `shade` is not finite).
