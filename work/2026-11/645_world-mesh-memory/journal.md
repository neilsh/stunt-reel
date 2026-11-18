# Journal

## 2026-11-18: where a LOCATION render's memory goes on lavapipe

- **Question**: Of the ~1 GiB a lavapipe render of LOCATION peaks at, how much is the world mesh's
  CPU copy, its device buffers, the upload's staging copies and the rest, and is any CPU copy kept
  that nothing reads after upload?
- **Method**:
  - A cloud session: Ubuntu's Mesa 25.2.8 (`llvmpipe (LLVM 20.1.2, 256 bits)`), 4 vCPUs, 16 GB,
    `main` `56a530d`, release build. LOCATION ticks 12-120 rendered headless with the parity
    pipeline's flags (`--tick-range 12..=120 --width 320 --height 200 --viewport-rows 185
    --software-only`), the `vault-location` capture's `LOCATION.ALL` and FreeFlight `SIDATA`.
  - Temporary probes, not committed, printed `VmRSS` and `VmHWM` from `/proc/self/status` after
    the scene was built, after the shapes and sprites were uploaded, after `plan_edges`, after
    the world's buffers were written, and after `Renderer::offscreen`; and the world's vertex,
    index, outline-index, node and `VERTEX_FLAG_LINE` counts and the `Vec` capacities. A shell
    loop sampled the process's `VmRSS` and `VmHWM` every 0.25 s.
  - Variants of the probe build, each beside `main`: the world mesh replaced with an empty
    `SodModelIr` right after `Renderer::offscreen`; that plus `MALLOC_ARENA_MAX=2`; that plus a
    `queue.submit` and `PollType::Wait` at the end of `SceneRenderer::new`. SHA-256 of
    `frames.zst`, `layers.zst` and `palettes.zst` against `main`'s.
- **Result**:
  - The world uploads as one chunk: 6,702,496 vertices (28 B), 7,488,138 indices, 12,861,990
    outline indices (`plan_edges`), 196,633 nodes; 268,704 vertices carry `VERTEX_FLAG_LINE`.
    The vertex and index `Vec`s each have capacity 8,388,608.
  - RSS on `main`, in MiB: scene built 300.9; device open with shapes and sprites uploaded 382.7
    (+81.8); outline list built 443.3 (+60.6); the world's three buffers written 699.9
    (+256.6, the 269,070,400 bytes of the vertex, index and outline buffers: the staging
    copies `write_buffer` makes); renderer open 687.2, `VmHWM` 749.0. The peak, 1,003 to 1,008
    MiB over four runs, comes in the first frames; RSS then settles at a median 817 to 829 MiB.
  - Emptying the world mesh after `Renderer::offscreen` drops RSS by 252.6 MiB at once; peak
    749 MiB (three runs), steady median 558 to 563 MiB. The stores are byte-identical to
    `main`'s over ticks 12-120 and 12-300.
  - With the forced submit and wait, `VmHWM` rises from 749.0 to 944.1 MiB during the wait and
    RSS settles at 765.5 MiB before the mesh is freed: lavapipe fills the device buffers' pages
    when the copy runs, while the staging copies are still held. On `main` that happens in the
    first frames, with the CPU mesh still held too, hence the peak.
  - `MALLOC_ARENA_MAX=2` leaves peak and steady RSS unchanged (749 and ~550 MiB).
- **Verdict**: control. The CPU copy of the world mesh is the only large copy nothing reads after upload
  (`FilmScene::frame` reads only `World::terrain` and `World::view_facing`; the start-up report
  and `export-gltf` read the mesh, before and without a renderer). Freeing it is the next entry.
  Ruled out: glibc arenas as a share of the plateau, and trimming the `Vec`s' spare capacity,
  which reallocation grows and nothing writes, so it should be address space, not resident memory;
  the 252.6 MiB released cannot tell that apart from the full capacity.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

## 2026-11-18: freeing the world mesh after upload

- **Question**: Does freeing the world mesh in the headless path, after `Renderer::offscreen` and
  before the first submit, lower peak and steady RSS on lavapipe and leave the render stores
  byte-identical?
- **Method**:
  - `FilmScene::release_world_mesh`, called by `run_headless` after each `Renderer::offscreen`
    (`342cc7a`, which is `main` `56a530d` plus this change), built in release beside `main`. Same cloud session and flags
    as the entry above.
  - LOCATION ticks 12-120 twice each, alternating `main` and the change; LOCATION ticks 12-300
    once each; CTRY's captured ticks (14-1333, from `tick_range_for_captured_ticks`) twice each,
    with `CTRY.ALL` from the `vault-ctry` capture. Peak is the largest `VmHWM` sampled; steady is
    the median `VmRSS` over the last 80% of the run. SHA-256 of the three stores per pair.
- **Result**:

  | Film, ticks | Peak, `main` | Peak, freed | Steady, `main` | Steady, freed | Wall, `main` | Wall, freed |
  |---|---|---|---|---|---|---|
  | LOCATION 12-120 | 1,004, 1,004 MiB | 748, 749 MiB | 823, 821 MiB | 563, 563 MiB | 9.1, 9.3 s | 9.4, 9.6 s |
  | LOCATION 12-300 | 1,004 MiB | 749 MiB | 827 MiB | 566 MiB | 20.8 s | 21.0 s |
  | CTRY 14-1333 | 139, 140 MiB | 139, 139 MiB | 136, 137 MiB | 136, 137 MiB | 4.4, 4.7 s | 4.4, 4.4 s |

  - LOCATION's peak falls by 255 MiB (25%) and its steady RSS by 260 MiB (32%). CTRY's world is
    20,044 vertices and 28,800 indices, so freeing it changes nothing measurable.
  - `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical before and after on both
    films: LOCATION 12-300 `1906dff0…`, `508783b9…`, `2537dc85…`; CTRY 14-1333 `cabd0799…`,
    `987b39b0…`, `da5bfabf…`.
- **Verdict**: adopted. The stores are identical and LOCATION's lavapipe peak falls from 1,004 to
  749 MiB. LOCATION's wall time is 0.2 to 0.3 s (1% to 3%) longer in all three pairs; with one
  or two runs each, and 0.2 s between identical runs here, that does not establish a cost. The
  GPU's figures and its byte check over every reference film's captured ticks are #645's
  `local-only` follow-up.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

## 2026-11-18: LOCATION's world at `48f5d49`

- **Question**: The 2026-11-06 entry measured LOCATION's render at about 300 MiB on the RTX 4070
  at `48f5d49`, as much as CTRY's. Was LOCATION's world smaller then, or does the 1,004 MiB peak
  above come from elsewhere?
- **Method**: `mise run build-at -- 48f5d49`, then LOCATION ticks 12-120 with the same flags and
  inputs as the entries above, less `--software-only`, which `48f5d49` lacks (the cloud session has
  no GPU, so it renders on the same lavapipe). The world's size from the start-up report line.
- **Result**: at `48f5d49` LOCATION's world is 158 terrain patches, 6,463 static props, 795,172
  vertices and 912,750 indices; the render peaks at 258 MiB, steady 252 MiB, 2.9 s. At `56a530d` it
  is 158 patches, 56,395 props, 6,702,496 vertices and 7,488,138 indices, peaking at 1,004 MiB.
- **Verdict**: control. LOCATION's world has grown about eightfold since `48f5d49`, which accounts
  for its render no longer costing what CTRY's does.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).
