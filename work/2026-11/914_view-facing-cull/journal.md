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
