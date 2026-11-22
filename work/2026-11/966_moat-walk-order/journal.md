# Journal

## 2026-11-22: The castle's moat, its green bank and the order PLAYONE paints them

- **Question**: which props are the castle's moat water and the green that `main`'s GPU draws in one-row stripes across it at `LOCATION` 3824 ([#966](https://github.com/neilsh/stunt-reel/issues/966)), how high each lies, how our world routes them, and in which order `PLAYONE` paints them.
- **Method**: static reads and one-tick renders, no score; base `b9441a06` (`crates` `d6edce87`, the tree the #637 entry of this date measured as `main`).
  `mise run frame -- --film location --ticks 3819,3829` on the RTX 4070 (3817 and 3824 are not captured; 3819 and 3829 are the nearest), and a scratch script reading the frame store's index plane and `shapes.zst` (`shape id + 1` of the prop that drew each pixel).
  `stuntreel sod-trace` and `export-gltf --shape` on the `vault-location` capture's `LOCATION.ALL` (`all_sha256` `4a427bdd…`) for `0x04AA`, `0x04AC` and `0x0539`.
  A temporary `eprintln!` in `build_world_ir` (not committed) for each placement's position, `SP_1NODE` chain, reach and ground snap.
  `scene_tree.walk_slot` on the unpatched image (`build/re/playone.img`) with no slot, from the eye of tick 3829 and three other eyes around the castle, and a scratch walk recording each leaf's path from the root.
- **Result**:
  - **The two props.** At tick 3829, in the 60 × 85 pixels at the frame's lower left, index 136 is drawn by `0x0539` (3,456 pixels) and index 193 by `0x04AC` (1,037) and `0x04AA` (200); no terrain pixel is there.
    `0x04AC` is one flat quad, `COLOR 0x00C1` (193), 128 × 132 m; `0x0539` is eleven flat polygons, each `COLOR 0x0088` (136), a 16 × 100 m strip with a curved edge.
    Both decode to `y = 0` in their shape, and both placements are at our `y = 75` m: `0x04AC` placement 14760 at `(-576, 75, -702)`, `0x0539` placement 14766 at `(-520, 75, -702)`.
    The strip lies wholly inside the moat quad in plan (`x` −528 to −512 and `z` −752 to −652 against −640 to −512 and −768 to −636), in its plane exactly.
    `0x04AA`, the moat's next quad (`y = 0.03125` in its shape, at `(-448, 75, -704)`), meets `0x04AC` along `x = −512` and does not overlap the strip.
  - **Our world.** Neither placement is a ground decal: the terrain under them is not within 10 cm of 75 m (ADR 0035's rule).
    Both are behind `SP_1NODE` gates (chains 5541 and 5543), so `push_gated_props` makes each a `WORLD_GATED` base node, drawn with depth write, and the exact coplanar tie goes to the depth compare: at 3829 rows 128 and 132 show water through the strip on the GPU, and the capture shows the strip whole.
    The ground pass ([ADR 0045](../../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md)) takes only faces within 10 cm of `y = base_y`, 75 m below.
  - **The paint order.** The leaves' paths from the root share every node down to `SP_2NODE` `0x80B2`: its `ptr` is the `SP_LEAF` `0x80C2` of `0x04AC`, and `0x0539`'s `SP_LEAF` `0x813A` is in its `next` chain (through `SP_1NODE` `0x80D0` and `0x80DA`, `SP_2NODE` `0x80E4` and `SP_LIST` `0x80EA`).
    `SP_2NODE` (`0x1EC0`) visits `ptr`, then `next`, with no eye test, so `PLAYONE` paints the moat, then the strip, from any eye; the four walks agree.
    Our placement order keeps the tree's: 14760 before 14766.
- **Verdict**: control (no render change).
  Not a near tie but an exact one, between two props off the ground plane; `PLAYONE` settles it by walk order, the strip over the water.
  The fix it points to is the decal pass, not the ground pass: the ground pass is for faces on `y = base_y` and is drawn before raised geometry with `Always`, which a plateau 75 m up cannot join without losing occlusion; a flat prop lying on an earlier flat prop is drawn after it as a decal of it, as ADR 0035 does for a flat prop lying on the terrain and section 6.5 of `world-scene-residuals.md` for a `MAP.BIN` patch lying on an earlier one.
- **Lives in**: [`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6.9.

## 2026-11-22: A flat prop lying on an earlier flat prop is a decal of it

- **Question**: whether drawing a flat prop that lies on an earlier flat prop as a decal of it (`DBG_PROP_OVERLAY=1`) paints `LOCATION`'s strip over the moat on both classes, and what else it moves.
- **Method**: track evidence: `SP_2NODE` at image `0x1EC0` visits `ptr` before `next` with no eye test (entry above; [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 3.1).
  The rule: a placement whose shape is flat (every vertex within 5 cm of one height) and not already a ground decal is a decal of the first earlier flat placement whose plan box contains its own and on whose triangles every one of its vertices lies, within 10 cm (`GROUND_LIE_TOLERANCE`); its vertices take that triangle's height, and `build_world_ir` routes it as it routes a ground decal.
  On `LOCATION` it picks 20 placements, among them `0x0539` (14766) and `0x0538` (14765).
  Sweep on the RTX 4070 over the seven reference films, flags as run:
  `mise run sweep -- --var DBG_PROP_OVERLAY=0,1 --record work/2026-11/966_moat-walk-order --topic prop overlays --track evidence --target location:3812-3968 --images work/2026-11/966_moat-walk-order/images`.
  Then, with the rule committed without the switch (`4c8d8f17`, `crates` `bddf5daf`) and `main` `b9441a06` (`crates` `d6edce87`) as the baseline, each in its own checkout: `mise run parity` on the RTX 4070 Laptop (driver 610.88), `mise run parity -- --software-only` in WSL 2 on the canonical lavapipe (`llvmpipe (LLVM 20.1.2, 256 bits)`, `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5`), `mise run agreement -- measure --gpu <root> --lavapipe <root>` on each tree, a scratch script summing `class_agreement.compare` over `LOCATION` 3812 to 3968, and `mise run judge -- <main reports> <fix reports> --track evidence --target location:3812-3968` for each class.
  (Measuring the switch's two values from one dirty tree was not possible: `measure` needs the reports to name a `crates` tree.)
- **Result**:
  - **Sweep (GPU)**: winner line `DBG_PROP_OVERLAY=1 adopts (evidence, film means; target idx +0.0013 attribution; worst target frame +0.0000 location:3928)`; target SSIM +0.0030.
    Every film's `mean_ssim_scored` is unchanged to four decimals; `LOCATION` rises from 0.8724649 to 0.8725229 (+0.0000580, under the 0.002 attribution bound), and no frame of any film falls by more than 0.005.
    Pictures: `images/location-{3829,3862,3895,3928,3961}-prop-overlays.png` (capture, baseline, rule); figures: `sweeps/prop-overlays.toml`.
  - **GPU, clean trees**: the same scores as the sweep; 14 `LOCATION` frames move, all from 3819 to 3961 and none down, the largest 3862 (+0.0090), 3840 (+0.0069), 3895 (+0.0059) and 3906 (+0.0053); no frame of another film moves.
    Judge: `run=candidate adopts (evidence, film means; target idx +0.0013 attribution; worst target frame +0.0000 location:3928)`.
  - **Lavapipe, clean trees**: `LOCATION` 0.87253666 to 0.8725389 (+0.0000022); 12 frames move, from 3819 to 3961, the largest 3829 (+0.0009), and one down, 3961 by 0.0000027.
  - **The other six films**: no pixel of any of their ticks changes on either class (their stores compared tick by tick, `main` against the rule).
    Judge: `run=candidate adopts (evidence, film means; target idx +0.0000 attribution; worst target frame -0.0000 location:3961)`.
    Lavapipe already drew the strip over the water on `main`, so it barely moves.
  - **Agreement**, mean differing pixels per tick, `main` then the rule: `LOCATION` 8.59 (584 at 3824, 3 ticks over 500) to 6.31 (359 at 780, none over 500); the other six films unchanged (CTRY 3.09, INTRO 2.22, LAND 5.23, BALLOON 4.12, TRAINTNL 3.66, BOMB 8.40), as the #637 entry of this date measured `main`. `measure` flags nothing on either tree.
  - **`LOCATION` 3812 to 3968** (157 ticks, every one differing on both trees): 20,736 differing pixels to 1,984, 132.08 to 12.64 a tick, the largest 584 at 3824 to 39 at 3860.
  - **The ticks `lavapipe.md` section 5 names** (GPU against lavapipe, index planes compared pixel by pixel with a scratch script): on `main`, 325 of the 335 differing pixels at 3815, 572 of 584 at 3824, 490 of 513 at 3828 and 560 of 575 at 3830 are the strip's 136 on one class against the moat's 193 on the other (308, 572, 490 and 560 of them the GPU's 193); with the rule those ticks differ by 11, 12, 23 and 15 pixels, none of them that pair.
  - **Cost** (release build, a temporary timer around `prop_overlay_vertices`, not committed, three runs): on `LOCATION` it tests 6,991 flat placements of 35,479 in 37 to 39 ms. 4,912 of them lie on an earlier flat prop, but all except 20 are ground decals already, which keep their terrain snap. With the `stisldem` `VAULT` archives, `INTRO` has 1,485 flat placements of 10,723 (2.3 ms) and `CTRY` 138 of 300 (0.15 ms).
- **Verdict**: adopted on the evidence track, every guard passing on both classes, and on #966's criterion: `LOCATION`'s three ticks over 500 differing pixels are gone and no film's mean rises.
  Expected tables repinned on `crates` `bddf5daf` for both classes (`94e5e21b`, `d004b13e`), and again, scores unchanged, on `crates` `59949192` after `ce4e203b` added tests (`0c6120a7`, `26792e7c`).
- **Lives in**: [`world-scene-residuals.md`](../../../research/playone-exe/world-scene-residuals.md) section 6.9; [ADR 0035](../../../docs/adr/0035-ground-lying-props-are-terrain-decals.md), amended; [`lavapipe.md`](../../../research/parity/lavapipe.md) section 5.

## 2026-11-22: Depth32Float again, on the fixed tree

- **Question**: whether `Depth32Float` agrees as well as `Depth24Plus` once the moat's tie is fixed, which would reopen [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md)'s format choice (#966's third acceptance item).
  The #637 folder is closed (its README has an `outcome`), so the re-measurement is recorded here.
- **Method**: track heuristic, no target frames. Candidate: commit `d9759e0e` (`DEPTH_FORMAT` `Depth32Float`, decal bias `constant: 32, slope_scale: 2.0`) cherry-picked onto `4c8d8f17` on a local scratch branch (`35054991`, `crates` `9aa6ee4c`, not pushed); baseline the rule's tree of the entry above.
  Rendered, measured and judged as there, on the same adapters and drivers.
- **Result**:
  - Mean differing pixels per tick, the rule in `Depth24Plus` then in `Depth32Float`, with the largest and its tick: CTRY 3.09 → 9.55 (148 at 811), INTRO 2.22 → 5.73 (140 at 3043), LAND 5.23 → 27.36 (264 at 382), BALLOON 4.12 → 46.23 (217 at 837), TRAINTNL 3.66 → 29.16 (231 at 875), BOMB 8.40 → 27.62 (219 at 2956), LOCATION 6.31 → 58.17 (556 at 4684).
    The six films other than LOCATION read as the #637 entry of this date read them for `Depth32Float` on `main`; LOCATION's mean falls from that entry's 80.23.
  - Ticks over 500 differing pixels: none of 3812 to 3968 (152 on `main` with `Depth32Float`), and the four the #637 entry also listed outside that range: LOCATION 4684 (556), 4784 (515), 4803 (505), 4810 (509).
    Over 3812 to 3968, 24,128 differing pixels, 153.68 a tick, the largest 339 at 3892, against 1,984 in `Depth24Plus`.
  - `measure` flags every film's mean against the pinned `agreement.toml`.
  - GPU judge against the rule in `Depth24Plus`: `none adopts (best run=candidate: film means short of +0.002 each or +0.004 on one)`; 4 frames fall by more than 0.005, LOCATION 4203 (−0.0143), 4214, 4236 and 4259.
    Lavapipe judge: the same winner line; 29 frames fall by more than 0.005 (15 LOCATION, 14 BALLOON), the worst LOCATION 4764 (−0.0164); LOCATION 3829, 3928 and 3961 among them (−0.0059, −0.0077, −0.0059).
- **Verdict**: rejected again. With the moat's tie gone, `Depth32Float` still makes the backends disagree 2.6 to 11 times more than `Depth24Plus` on every film, LOCATION included (9.2 times); it does not agree as well, so ADR 0054's format choice is not reopened.
  Within 3812 to 3968 it still disagrees more than `main` did in `Depth24Plus` (153.68 against 132.08 a tick); that residue was not attributed.
- **Lives in**: [ADR 0054](../../../docs/adr/0054-depth-is-reversed-and-infinite.md), Status and Considered Options.
