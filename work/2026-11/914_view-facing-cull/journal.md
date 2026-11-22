# Journal

## 2026-11-22: culling view-facing props on the cloud's lavapipe

- **Question**: Does the real `#914` change, skipping a view-facing prop whose model box lies outside the view frustum, leave every render store byte-identical on lavapipe, and how much render time does it save?
- **Method**:
  - Branch `claude/project-thread-483x4x` at `3e26dea` against `main` `dab2184`: `GpuModel::bounds` is the union of the model's root subtree boxes, and `SceneRenderer::prepare` skips a `view_facing` draw when `frustum_keeps(rotation_proj * eye-relative model matrix, bounds)` is false, before its walk.
  - A cloud session (4 vCPUs, Ubuntu 24.04 `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5`, `llvmpipe (LLVM 20.1.2, 256 bits)`, `LP_NUM_THREADS` unset).
  - `mise run parity -- --software-only` on each tree, all seven reference films, then `cmp` of every `build/parity/ours/<film>_current/*.zst`.
  - Each tree's release binary rendered Span A (`LOCATION 12..=300`, 289 ticks), Span B (`LOCATION 3680..=3979`, 300 ticks) and Span C (`INTRO 2500..=2949`, 450 ticks) with the parity pipeline's argv (`--at-ticks`, `--width 320 --height 200 --viewport-rows 185 --software-only`), three rounds interleaving the two binaries, timed as whole-process wall clock (scene build and renderer open included), and SHA-256 of the four stores.
- **Result**:
  - Seven films: 28 of 28 `.zst` files byte-identical, and the seven score lines unchanged (`location` SSIM 0.8722, IoU 0.9820, 732/745 scored).
  - Spans: all six runs of each span share one SHA-256 per store across both trees:
    - Span A: `frames.zst` `7c6aa0d1584be8c60ce12685f2ec92d4c570326491e086257f4b5ef0cdca1695`, `layers.zst` `8f89fdc5eef69d35283849dec8f03a3e6929846c95b30aed5b5b7d72c4598b5b`, `palettes.zst` `2537dc858937720397d4220fc3f8678c092f49ec0c81ff445fb5041d93ec2aab`, `shapes.zst` `3b7330d8d3e862b038c45875993f8e0f018d0f733932122463993c70b183fe09`.
    - Span B: `frames.zst` `440bfdcb7bffb2d5da7191a250f53b348058b6c866c36e734799a74d1e777300`, `layers.zst` `9e27d22d8497dcc5ca1896413cd58fad45dacaa70b6746d41d6973d7f0ff6d53`, `palettes.zst` `8693c7227b8eee0d4b00710ea14781bb5c1526e27533fc9336e04d84a54e5cbb`, `shapes.zst` `03d23b4d4679edf258a48db72e4e3ffa2ca23cc9104ef409062a054549b876b3`.
    - Span C: `frames.zst` `a4086c5d3d0750d0607afdb6e1b4ff387f09c4ce701389f6bfb024ded9e359f8`, `layers.zst` `d15f45c4126051d3c5cbd78cdcb8f2b7cf9344953931d7ee3dce4c6b9bf1b4ff`, `palettes.zst` `8693c7227b8eee0d4b00710ea14781bb5c1526e27533fc9336e04d84a54e5cbb`, `shapes.zst` `bc0dd273939cbe5d9c7037d22ef6a4da10c9d813e31eddc2a4961896fafc991f`.
  - Whole-process wall clock, seconds, before and after (three runs each, sorted):

    | Span | `dab2184` | `3e26dea` | Median change |
    |---|---|---|---|
    | A `LOCATION 12..=300` | 15.923, 15.951, 16.806 | 4.082, 4.545, 4.662 | -71.5% (3.51x) |
    | B `LOCATION 3680..=3979` | 10.851, 11.927, 12.186 | 6.128, 6.438, 6.449 | -46.0% (1.85x) |
    | C `INTRO 2500..=2949` | 21.399, 21.678, 22.983 | 4.032, 4.084, 4.853 | -81.2% (5.31x) |

- **Verdict**: adopted: no pixel of any store moves on lavapipe, and every span renders faster.
  These are whole-process figures, so they include the fixed scene build and renderer open that `#918`'s loop-only figures leave out.
- **Lives in**: [`research/parity/lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).

## 2026-11-22: the cull on the RTX 4070 and on Windows lavapipe

- **Question**: Does the same change leave the GPU's stores byte-identical, and what does it save on the machine `#918` measured?
- **Method**:
  - The owner's laptop, `main` `dab2184` against the branch at `3e26dea`, each in its own worktree.
  - `mise run parity` on the `NVIDIA GeForce RTX 4070 Laptop GPU`, all seven reference films, then SHA-256 of every `build/parity/ours/<film>_current/*.zst`.
  - Each tree's release `stuntreel.exe` rendered Span A on the GPU, and Spans A, B and C on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `--software-only`), with `--headless --tick-range <span> --width 320 --height 200 --viewport-rows 185`, three interleaved runs per tree, timed as whole-process wall clock.
- **Result**:
  - GPU parity: 28 of 28 `.zst` files byte-identical; both trees scored the same to seven decimals (`location` SSIM 0.8721, IoU 0.9820, 732/745 scored).
  - Each span's stores were byte-identical across all six runs: Span A on the GPU, and Spans A, B and C on Windows lavapipe (which rendered none of the seven films).
  - Whole-process wall clock, seconds, median (min, max):

    | Span | Adapter | `dab2184` | `3e26dea` | Median change |
    |---|---|---|---|---|
    | A `LOCATION 12..=300` | RTX 4070 | 3.01 (2.98, 3.02) | 2.57 (2.56, 2.61) | -14.6% (1.17x) |
    | A `LOCATION 12..=300` | lavapipe | 8.11 (7.90, 8.40) | 2.82 (2.81, 2.87) | -65.2% (2.88x) |
    | B `LOCATION 3680..=3979` | lavapipe | 6.56 (6.55, 6.74) | 4.02 (4.00, 4.10) | -38.7% (1.63x) |
    | C `INTRO 2500..=2949` | lavapipe | 9.44 (9.41, 9.46) | 2.64 (2.62, 2.65) | -72.0% (3.58x) |

- **Verdict**: adopted: no pixel moves on the GPU or on Windows lavapipe, and every span renders faster.
- **Lives in**: [`research/parity/lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).

## 2026-11-22: keeping disc props under a zoomed lens

- **Question**: A review found that `squeeze_disc` rescales a disc rim vertex's clip `z` and `w` about the disc's centre by `disc_depth_scale`, the lens zoom, so under a lens other than the default a rim vertex outside the model box's side planes can move into the view; does keeping such props cost the cull's gain?
- **Method**: `GpuModel::in_frustum` now keeps a model holding any `VERTEX_FLAG_DISC` vertex whenever the camera's `disc_depth_scale` is not 1.
  On the cloud session of the first entry, the release binary rendered Spans A, B and C three times each, and `mise run parity -- --software-only --no-build` ran the seven films; stores were compared with `dab2184`'s.
- **Result**: Every store byte-identical again: the three spans' four files each, and 28 of 28 files over the seven films.
  Whole-process wall clock, seconds: Span A 5.009, 5.096, 5.119 (median 5.10, against 4.55 without the guard and 15.95 on `dab2184`: `-68.1%`); Span B 6.010, 6.325, 6.550 (median 6.33, `-47.0%`); Span C 3.645, 3.811, 4.027 (median 3.81, `-82.4%`).
  Span A's camera uses a 22.1-degree lens, so its disc props are no longer culled; Spans B and C did not slow.
  The GPU and Windows lavapipe were not re-run with the guard.
- **Verdict**: adopted: the guard closes a hole the stores could not show, at about half a second on Span A.
- **Lives in**: [`research/parity/lavapipe-render-time.md` § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).

---

## 2026-11-22: culling actor bodies, shadows and sprites, and the world's disc gap

- **Question**: After `#930`, does culling the other three non-world loops of `SceneRenderer::prepare` (actor bodies, actor shadows, placed sprites) save render time on lavapipe or the RTX 4070, and does `#644`'s world cull drop a disc rim vertex that `squeeze_disc` brings into the view under a zoomed lens?
- **Method**:
  - The owner's laptop (Ryzen 7 7745HX, Windows 11, on AC), mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` and `--software-only`) and the `NVIDIA GeForce RTX 4070 Laptop GPU`, `main` at `9ccfd39c`.
    Other agent sessions ran on the machine throughout, so the later runs of every cell are up to twice as slow as the earlier ones; each cell below reports its minimum, the median of its four fastest runs and the median of all eight.
  - Before coding, `#931`'s probe on `main` (one run per cell) for the two phases the issue asks for: `prepare_actors_other` plus `prepare_sprites_place` were `0.44%`, `0.25%` and `0.96%` of the loop on lavapipe (Spans A, B, C: `LOCATION 12..=300`, `LOCATION 3680..=3979`, `INTRO 2500..=2949`) and `0.56%`, `0.51%` and `1.19%` on the RTX 4070.
    Those phases are the CPU preparation only, so the saving from fewer submitted draws was measured too: an upper bound, skipping every actor and its relight (a throwaway switch), cut the loop `20%` (Span A) and `22.5%` (Span C) on lavapipe and left Span B unchanged (`+1%`), which says what the actors cost, not what their off-screen draws do.
  - The whole change, as the issue designed it, in [`actor-sprite-cull.patch`](actor-sprite-cull.patch) on `9ccfd39c`: `GpuNode::discs`, `rewrite_vertices(&mut self)` refreshing every box, `ViewTest`/`ActorView` testing each body and shadow by its own matrix (the rest pose's box before the relight at `AngleBank::REST`, the posed model's after), sprites tested before `place_sprites`, the world walk keeping a node with discs under a zoomed lens, and the tests for each.
  - Draw and time figures from one throwaway binary built from that patch with three environment switches (not committed): `DBG_NO_CULL` takes the actor, shadow and sprite tests out, `DBG_NO_WORLD_GUARD` the world's disc guard, `DBG_COUNT` prints per-frame slice counts and the render loop's milliseconds, so before and after are the same binary.
    Eight runs per cell, the two variants in random order.
  - `mise run parity` on the RTX 4070 and on lavapipe, on `main`'s binary and on each head, then SHA-256 of every `build/parity/ours/<film>_current/*.zst` and `mise run parity-residue` between the two roots.
- **Result**:
  - **The full cull moved no pixel.**
    On both adapters 28 of 28 store files were byte-identical to `main`'s, `parity-residue` counted `0` differing index-plane pixels on every film (`balloon`, `bomb`, `ctry`, `intro`, `land`, `location`, `traintnl`), and every score line matched to the printed digits.
  - **It cut the draws and not the time.**
    Draw slices per frame, `main` then full cull, median (mean, max):

    | Span | Actor bodies | Shadows | Sprites | World |
    |---|---|---|---|---|
    | A | `110` (`110.3`, `114`) -> `82` (`82.3`, `86`) | `50` -> `50` | `0` -> `0` | `16` (`25.0`) -> `23` (`32.0`) |
    | B | `110` (`111.6`, `128`) -> `0` (`1.5`, `49`) | `51` (`50.2`) -> `0` (`1.5`, `49`) | `0` -> `0` | `915.5` -> `915.5` |
    | C | `257` (`243.9`, `284`) -> `139` (`146.3`, `283`) | `126` (`154.3`, `221`) -> `124` (`93.6`, `218`) | `0` (mean `0.1`) -> `0` (mean `0.1`) | `34` (`32.6`) -> `36` (`33.9`) |

    Render loop, milliseconds, `main`-equivalent then full cull (minimum / median of the four fastest / median of eight):

    | Span | Adapter | Without the culls | With them | Change (four fastest / all eight) |
    |---|---|---|---|---|
    | A | lavapipe | `1578` / `1620` / `1722` | `1593` / `1658` / `1726` | `+2.4%` / `+0.3%` |
    | B | lavapipe | `2776` / `2809` / `2870` | `2770` / `2843` / `2917` | `+1.2%` / `+1.6%` |
    | C | lavapipe | `2506` / `2597` / `2671` | `2456` / `2501` / `2635` | `-3.7%` / `-1.4%` |
    | A | RTX 4070 | `1055` / `1156` / `1215` | `1061` / `1076` / `1098` | `-6.9%` / `-9.7%` |
    | B | RTX 4070 | `1015` / `1086` / `1200` | `1049` / `1155` / `1286` | `+6.3%` / `+7.2%` |
    | C | RTX 4070 | `1737` / `1815` / `2009` | `1707` / `1741` / `1937` | `-4.1%` / `-3.6%` |

    The sign changes with the span and the statistic, and a cell's own runs spread by more than the change (Span B on lavapipe: `2776..4963` ms across the eight runs of one variant), so no cell shows a saving.
    Span B drops every actor and shadow draw (`161` of about `1,080` slices per frame) and its lavapipe loop stays at `2.8 s`.
  - **The world cull has the gap.**
    `a_squeezed_rim_vertex_can_enter_the_view_from_a_culled_box` builds a disc whose centre and rim vertex both lie outside the left plane, so `frustum_keeps` rejects their box, and applies `squeeze_disc`'s arithmetic at a depth scale of 2: the rim vertex's `x / w` falls from beyond `1` to inside it.
    `the_world_walk_keeps_a_disc_node_beside_the_view_under_a_zoomed_lens` fails with the disc test taken out of the walk, as `main`'s walk has it (the node is dropped: `0` slices against `1`), and passes with a per-node disc flag.
    The seven films' stores do not show it: the guard left all 28 files of both adapters byte-identical to `main`'s, so on those films no culled world node holds a rim that squeezes in.
  - **The guard's cost is small and unresolved.**
    On lavapipe the guard raised the world's draw slices per frame from `16` to `23` (Span A, a 22.1-degree lens: `7,235` to `9,258` over the span), `915.5` to `915.5` (B) and `34` to `36` (C).
    Loop, same switches, eight runs, change of the four fastest / of all eight against the unguarded: lavapipe A `-3.2%` / `-6.4%`, B `-4.7%` / `-1.5%`, C `-2.3%` / `-5.0%` (a guard cannot speed a render, so these are the runs' spread); RTX 4070 A `+2.8%` / `+1.9%`, B `+6.0%` / `+10.0%`, C `+9.0%` / `+5.4%`, with the minimum of each cell lower with the guard (`-9.5%`, `-8.1%`, `-12.2%`) than without it.
    Two draws more per frame on Span C cannot cost `9%`: these are spreads of the same size as the actor cull's, not a cost.
  - The landing diff (the world guard alone), rendered on the RTX 4070 and on lavapipe: 28 of 28 files byte-identical to `main`'s on each, `parity-residue` `0` on every film, score lines unchanged; the RTX 4070's run is the lens re-check `#930` asked for.
- **Verdict**: the actor, shadow and sprite culls are a no-go: they remove `25%` (A), `100%` (B) and `46%` (C) of the actor-body slices per frame, and up to all of the shadows (`100%` on B, `1.6%` on C's median), yet move no loop time out of the spread, on either adapter, and the CPU phases they shorten are `0.25%..1.2%` of the loop, below the issue's 3% bar.
  Only the world's disc guard lands: a per-node disc flag, `collect_world_meshes` taking the camera's `disc_depth_scale`, and the tests above.
  The patch stays for a later reader who finds an actor-heavy span where off-screen actors cost; it applies on `9ccfd39c`.
- **Lives in**: [`lavapipe-render-time.md` § 3 and § 6](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes).
