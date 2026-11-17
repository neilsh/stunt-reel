# Journal: distilling `lavapipe.md`

The dated rounds and superseded results of [`lavapipe.md`](../../../research/parity/lavapipe.md) as of commit `16eb34e`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed; a section number in the moved text names a section of the note as it stood at `16eb34e` (`git show 16eb34e:research/parity/lavapipe.md`), and "this section" or "above" means that section there.

## 2026-11-07: Candidate fixes for the NaN shade

Lavapipe only; a `DBG_SHADE` sweep plus one `mise run parity` per candidate, on `b0c90c2` and `9f04164` (identical renderer); (c) adopted, then (d) and (e) on top of it. `mean_ssim_scored` CTRY / INTRO, IoU 0.9897 / 0.9856 in every row, then index agreement:

* base (`linear`, rounded): 0.6446 / 0.6040; 0.663 / 0.612.
* (a) `shade` `@interpolate(perspective)`: 0.8722 / 0.8281; 0.8893 / 0.8289. Not byte-identical on a GPU: a Gouraud (`GVPOLY`) polygon's index becomes perspective-correct instead of screen-linear, which departs from PLAYONE's filler ([`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) section 6). Its lavapipe stores differ from (c)'s.
* (b) flat `palette_index` unless the polygon is Gouraud, marked by a temporary vertex flag bit 3 set in `tessellate.rs` when `vertex_palette` is non-empty: 0.8722 / 0.8281; 0.8893 / 0.8289. On a GPU it should be byte-identical: flat polygons already round to their own index, and Gouraud ones keep `linear`. It needs a `SodVertex` flag (a seam-contract change), and Gouraud polygons stay exposed on lavapipe: its INTRO store differs from (c)'s, its CTRY store does not.
* (c) guard, adopted: a non-finite `shade` (exponent bits all set) falls back to the flat `palette_index`: 0.8722 / 0.8281; 0.8893 / 0.8289. Shader-only; the RTX 4070's index planes are byte-identical with and without it (section 4). On lavapipe a Gouraud polygon hit by the bug drew its provoking vertex's index instead of its gradient until (d), whose gradient was one index off on some pixels until (e) (section 5).
* (b) and (c) together: byte-identical to (c) on lavapipe on both films.
* flat `palette_index` everywhere (diagnostic, drops `GVPOLY` interpolation): 0.8721 / 0.8231; 0.8895 / 0.8282.

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 3, The fix.

## 2026-11-15: What still differed on `52d84e6`

`[Bounded Observation]`, 2026-11-15, mesa-dist-win 25.2.8 against the RTX 4070, `crates` `52d84e6`. With the guard, lavapipe differs from the GPU by 22.6 to 147.4 index-plane pixels per tick on average over each film (CTRY 22.6, INTRO 29.3, LAND 119.2, BALLOON 43.5, TRAINTNL 62.5, BOMB 98.6, LOCATION 147.4). The ticks with the largest solid regions of difference (pixels whose four neighbours also differ):

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 5, What still differs; the ticks it introduces are the entries of 2026-11-16 below, and its per-film figures, BALLOON aside, match the Before column of the note's eye-relative table, measured on `3a7afb76`.

## 2026-11-15: A first local LOCATION run on a guard-removed binary

A first local LOCATION run scored 0.6344817 (563 frames down more than 0.005). Its binary was a guard-removed build left in `target/release` by the byte-identity check and reused with `--no-build`: its embedded WGSL has no guard, and its damage at LOCATION 3994, 4005, 4445 and 4467 matches a guard-removed render of those ticks pixel for pixel (43,216 of index 195 to 0 at 3994). Rendered again with the guard, LOCATION scores 0.8292054 (IoU 0.9784023, index agreement 0.8405, as the GPU's). _Source: [Lavapipe beside the GPU on one crates tree](../265_lavapipe-parity/journal.md#2026-11-15-lavapipe-beside-the-gpu-on-one-crates-tree)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 4 and Ruled out.

## 2026-11-15: One model-matrix upload per frame

`SceneRenderer::prepare` wrote each draw's model matrix with its own `write_buffer`, and wgpu allocates a staging buffer per call. On lavapipe that allocation (`gpu_allocator::FreeListAllocator::allocate`) held about half of 30 main-thread samples, the rest waiting in `wait_for_fence`, with the process at 1.00 core whatever `LP_NUM_THREADS` was. Why the allocation costs more on lavapipe than on the NVIDIA driver is not measured. #596 packs a frame's matrices into one uniform buffer at dynamic offsets, uploaded with one `write_buffer`:

| Run | Before | After |
|---|---|---|
| lavapipe, LOCATION ticks 12-300 | 150.5 s | 81.8 s |
| GPU, LOCATION ticks 12-300 | 20.9 s | 16.0 s |
| GPU, LOCATION's captured ticks (12-8262) | 301.2 s | 229.6 s |
| GPU, INTRO's captured ticks (12-3818) | 96.8 s | 67.8 s |

The render stores (`frames.zst`, `layers.zst`, `palettes.zst`) are byte-identical before and after, on lavapipe over LOCATION ticks 12-300 and on the GPU over every reference film's captured ticks. After the change, 16 of 20 main-thread samples sit in `wgpu_hal::vulkan::DeviceShared::wait_for_fence`, inside `vulkan_lvp`, and none in staging allocation. All-thread samples put lavapipe's work on one `vulkan_lvp` thread, the one that executes command buffers (busy in 52 of 65), while the other `vulkan_lvp` threads stay parked on a condition variable, and the offscreen target waited for each frame's readback, so the main thread and that thread did not overlap — the serialisation #602 removed (below). Mesa-dist-win ships no PDBs, so the thread's functions are known by offset only ([#600](https://github.com/neilsh/stunt-reel/issues/600)). On the GPU only the main thread is busy: of 42 samples, 14 in wgpu's render-pass encoding, 11 waiting on the GPU and 8 in `GpuModel::collect_world_meshes`. _Source: [2026-11-15: where a frame's time goes after the change](../596_lavapipe-staging-buffers/journal.md#2026-11-15-where-a-frames-time-goes-after-the-change), [2026-11-15: one model-matrix upload per frame](../596_lavapipe-staging-buffers/journal.md#2026-11-15-one-model-matrix-upload-per-frame)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 6, Render time.

## 2026-11-15: Two frames in flight

**Two frames in flight (#602).** `[Bounded Observation]`, 2026-11-15, `5844b4b8` before and the
issue-602 tree after, mesa-dist-win 25.2.8 and the RTX 4070 laptop, LOCATION ticks 12-300, one
headless process per run at 320×200. The headless loop now submits tick N+1 before it maps tick
N's readback buffers, and waits only for tick N's own submission; pages still reach the sink in
tick order. Each binary was timed twice, the second round with the after binary first:

| Run | Before | After |
|---|---|---|
| lavapipe, LOCATION ticks 12-300 | 88.7 s, 89.9 s | 76.3 s, 78.2 s |
| GPU, LOCATION ticks 12-300 | 16.7 s, 16.6 s | 12.4 s, 12.6 s |

The render stores are byte-identical before and after, on lavapipe over LOCATION ticks 12-300 and
on the GPU over every reference film's captured ticks, 20,621 ticks in all: each of the 21 file
pairs matches, and the seven `mise run parity` score lines do not move. The 81.8 s lavapipe row
above was measured on `80a3ad5`, the branch behind #601; this machine measured 88.7 s for
`5844b4b8`, so the paired rounds here, not that row, are the comparison.

_Source: [Two frames in flight in headless capture](../602_headless-capture-two-frames/journal.md#2026-11-15-two-frames-in-flight-in-headless-capture)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 6, Render time.

## 2026-11-16: Draws per frame

**Draws per frame (#603).** `[Bounded Observation]`, 2026-11-16, `b0f6c120` with a temporary
counter in `SceneRenderer::draw`, LOCATION ticks 12-300, on mesa-dist-win 25.2.8 and the RTX 4070,
which printed one line per frame and the same 289 lines on both. The median frame encodes 127,910
`draw_indexed` calls: 8,963 world ground fills and 6,269 ground outlines, 49,257 world base fills
and 45,560 base outlines (94,817 calls, 74.1% of the total), 5,550 world decal fills and 5,549
decal outlines, and 6,762 prop, actor and sprite fills. The world uploads as one chunk of
6,702,496 vertices and 7,488,138 indices, so every base slice draws with base vertex 0 from its
own index range; the base walk takes siblings last first while the IR numbers nodes in creation
order, so a parent's child slices come out in the reverse of their index order, and in each of
the 289 frames no adjacent pair of base slices continued the previous one's index range.
Coalescing contiguous base slices in walk order therefore removes 0 fill and 0 outline calls in
each of the 289 frames, against the 25% bar #603 set, so #603's decision is no-go; the counts
replace its estimate of a hundred to a thousand world mesh slices per frame.
_Source: [Draws per frame, and coalescing adjacent base slices](../603_draw-counts-per-frame/journal.md#2026-11-16-draws-per-frame-and-coalescing-adjacent-base-slices)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 6, Render time, and Ruled out.

## 2026-11-16: A perspective copy of the shade

* (d) (c) plus a `perspective` copy, adopted (#595; `[Bounded Observation]`, 2026-11-16, mesa-dist-win 25.2.8 and the RTX 4070, on `origin/main` `03356d6e`'s renderer): where `shade` is not finite, `fragment_index` rounds `@interpolate(perspective) shade_perspective` instead, and falls back to `palette_index` only when that is not finite either. `interp()` gives a perspective attribute the 3D weight `t` (section 2), so a Gouraud polygon the clipper breaks keeps a gradient. At BALLOON 145 its 4,044 pixels go from a flat 168 to 170 and 169: 2,954 match the GPU and 1,090 are one index off, since the GPU's gradient is screen-linear. Lavapipe's `mean_ssim_scored` and `mean_iou_scored` are the same with and without it on all seven films (BALLOON 145 is rendered but not scored), and the RTX 4070's `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical to those of `origin/main`'s shader over every reference film's captured ticks. The GPU test `a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient` draws a single index on lavapipe without it. _Source: [A perspective copy of the shade](../595_lavapipe-residues/journal.md#2026-11-16-a-perspective-copy-of-the-shade-for-gouraud-polygons-the-clipper-breaks)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 3, The fix, and Ruled out.

## 2026-11-16: The screen-linear ratio at BALLOON 145, before and after

* **A Gouraud polygon the clipper breaks** (BALLOON 145, drawn flat before (d)): the clipper's NaN hit a Gouraud (`GVPOLY`) polygon, and the guard drew its provoking vertex's index over the whole polygon: the GPU draws a 169-171 gradient over 4,044 pixels where lavapipe drew a flat 168, and the sentinel build marks exactly those 4,044 pixels non-finite. Candidate (d) (section 3) drew a gradient there, one index off the GPU's on 1,090 of the 4,044 pixels, and candidate (e) draws the GPU's: `[Bounded Observation]`, 2026-11-16, mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`) against the RTX 4070 laptop, before on `origin/main` `3a7afb76` and after on the same tree with (e) (`ba40ea63`). A local sentinel build (non-finite `shade` draws 250, never committed) marks 4,044 clipper-broken pixels at BALLOON 145 on lavapipe, the count above. Before (e), 2,954 of the 4,044 match the GPU and 1,090 are one index lower than it (977 are 169 against 170, 113 are 170 against 171), and 1,097 pixels of the whole frame differ; after, all 4,044 match and 7 pixels of the frame differ. The GPU draws 170 on 3,784 of the 4,044, 169 on 147 and 171 on 113. Mean index-plane pixels differing from the GPU per tick, with the largest difference and its tick, before then after (both on `3a7afb76`'s tree, so before eye-relative transforms landed in #650; the per-film figures after #650 are in the paragraph on it below):

  | Film | Before | After |
  |---|---|---|
  | CTRY | 22.6, 143 (840) | 22.6, 143 (840) |
  | INTRO | 29.3, 948 (2723) | 29.3, 948 (2723) |
  | LAND | 119.2, 3,290 (227) | 119.2, 3,290 (227) |
  | BALLOON | 41.0, 1,097 (145) | 40.0, 241 (144) |
  | TRAINTNL | 62.5, 301 (1079) | 62.5, 301 (1079) |
  | BOMB | 98.6, 587 (1915) | 98.6, 587 (1915) |
  | LOCATION | 147.4, 5,754 (2618) | 147.4, 5,754 (2618) |

  Only BALLOON's row moves. Diffing the two lavapipe stores directly (`mise run parity-residue`, before against after) gives 1,092 differing index-plane pixels on BALLOON and none on the other six films: 1,090 at tick 145, all inside the 4,044 sentinel-marked pixels, and 2 at tick 143, where lavapipe's 49 becomes the GPU's 50 (that tick's differences from the GPU go from 50 to 48), not traced to a broken polygon. Tick 145's differences from the GPU go from 1,097 to 7, and BALLOON's means from 41.0 to 40.0 over its 1,179 ticks; the counts at LAND 227 (3,290), BOMB 1910 (583), LOCATION 2599 (5,638) and 2859 (5,736) are unchanged. The BALLOON figure of 43.5 in the first sentence of this section was measured on `52d84e6`, before (d). On the RTX 4070, `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical to `origin/main`'s over each of the seven films' captured ticks, against `3a7afb76`'s stores (the branch before its merge of main, `ba40ea63`), against `857f80a8`'s (the merge `762680e0`), and, after #650's eye-relative transforms, against `origin/main` `e6fb29ce`'s (the merge `e6951d21`, which also changes the gradient test to project through `rotation_proj`): 21 of 21 files each time. `mise run judge --track evidence` moves no scored frame on either backend, and on lavapipe `mean_ssim_scored` and `mean_iou_scored` differ by 0.0000000 (the tables' seven decimals) on all seven films (these lavapipe comparisons are on `ba40ea63` against `3a7afb76`; lavapipe was not re-rendered on `857f80a8`, `e6951d21` or `e6fb29ce`). BALLOON 145 is rendered but not a scored frame. _Source: [The screen-linear ratio for the clipper's Gouraud polygons](../635_screen-linear-gouraud/journal.md#2026-11-16-the-screen-linear-ratio-for-the-clippers-gouraud-polygons)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 3, The fix, and § 5, What still differs.

## 2026-11-16: Which polygon each backend draws at the four residue ticks

* **A near-coplanar polygon wins the depth test** (LAND 227, BOMB 1910, LOCATION 2599 and 2859; eye-relative transforms remove all four, below; `[Bounded Observation]`, 2026-11-16, `origin/main` `03356d6e` with an uncommitted diagnostic that wrote each fragment's pipeline, provoking `vertex_index` and depth into the colour target). On the residue pixels the two backends draw different polygons whose depths lie close together. At each pixel where both were read alone (all but 16 of LAND's 3,222), the GPU puts the polygon it shows in front by 6e-8 to 4.5e-4: at most 3.3e-6 at LAND 227, 4.5e-4 at BOMB 1910, 6.3e-6 at LOCATION 2599 and 6.6e-6 at 2859. Lavapipe puts that polygon level or behind at every one of those pixels. Each depth below is the median over the residue pixels with that polygon's pipeline drawn alone, and each shift is the median of the per-pixel differences:
  * LAND 227, 3,222 pixels: the GPU draws a world prop (base pipeline, index 13), lavapipe a world ground polygon (ground pipeline, index 195). The ground pipeline compares `Always` and writes depth, so the prop's `Less` test decides. The ground lies at 0.9940678 on both; the prop at 0.9940665 on the GPU, 1.3e-6 in front, and 5.8e-6 further on lavapipe, behind. That ground polygon is flat in effect (the GPU's `shade` is 195.0 to 195.00003 over all 37,179 of its pixels), so this is not a Gouraud polygon drawn flat: 2,686 of the 3,222 pixels read non-finite, so the clipper broke the ground polygon (inferred from the NaN, by section 2's mechanism), and the guard draws its own index, 195, there.
  * BOMB 1910, 506 pixels in actor layer 17: the GPU draws a decal (index 7) over a base polygon of the same actor (index 35); on lavapipe the decal fails `LessEqual`. Rasterised depth, bias included: base 0.4169038 and decal 0.4166681 on the GPU, the decal 2.4e-4 in front; 0.4170929 and 0.4171583 on lavapipe, 6.5e-5 behind.
  * LOCATION 2599, 5,519 pixels: the ground (index 14) lies 3.2e-6 in front of a prop (index 169) on the GPU (0.9941396 against 0.9941428); lavapipe moves the ground 2.7e-6 back and the prop 4.2e-6 forward, so the prop shows.
  * LOCATION 2859, the same two polygons on 5,626 pixels: the prop lies 2.9e-6 in front on the GPU (0.9942664 against 0.9942693); lavapipe moves the ground 4.9e-6 forward and the prop 2.0e-6 back, so the ground shows. The ground's `shade` reads NaN there: the clipper broke it.

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 5, What still differs.

## 2026-11-16: The vertex stage at the four residue ticks

The vertex stage already differs (`[Supported Inference]`): comparing each polygon both backends draw by its provoking vertex's clip-space z bits, z differs in 133 of 306 polygons at LAND 227 (by up to 2,048 ulp), 89 of 313 at BOMB 1910 (16,384 ulp) and 67 of 231 at LOCATION 2859 (128 ulp); at BOMB 1910 the decal's provoking vertex leaves the vertex stage at z 0.35546875 on the GPU and 0.35595703 on lavapipe. Clipping is not the only source of the depth differences: polygons whose pixels stay off the viewport's edge differ too, by a median of 986 D24 units (2^-24 each) at LAND 227 and 67 to 74 at LOCATION, and LOCATION 2859's broken ground moves by about 82 units, against a median of 74 for the polygons off the edge in the same frame. The samples are small (7 to 16 polygons reaching the edge per tick), and at BOMB 1910 the polygons reaching the edge differ more (median 1,034 over 10, against 33 over 2 off it). Whether the clipper adds to a broken polygon's depth error is not separated from this, and why the two compilers round the transform differently is not shown. Both backends take `X8_D24_UNORM_PACK32` for `Depth24Plus`. _Source: [Which polygon each backend draws](../595_lavapipe-residues/journal.md#2026-11-16-which-polygon-each-backend-draws-at-the-four-residue-ticks)._

**Lives in** [`lavapipe.md`](../../../research/parity/lavapipe.md), § 5, What still differs.
