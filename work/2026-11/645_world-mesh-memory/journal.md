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
    (`342cc7a`, which is `main` `56a530d` plus this change), built in release beside
    `main`. Same cloud session and flags
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
- **Verdict**: control. LOCATION's world has grown about eightfold since `48f5d49` (vertices 8.4x,
  props 8.7x) and its lavapipe render's peak 3.9x, which is consistent with the world mesh being
  why its render no longer costs what CTRY's does; no breakdown was taken at `48f5d49`.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

## 2026-11-18: where a CTRY render's memory goes on lavapipe

- **Question**: The entries above break down LOCATION's peak; where does CTRY's go, whose world is
  20,044 vertices?
- **Method**: the same cloud session's lavapipe and flags as the entries above, `main` `9c9c6a5`
  (after the mesh is freed), release build. A temporary probe, not committed, printed `VmRSS` and
  `VmHWM` from `/proc/self/status` on entering `run_headless` (scene built), after
  `Renderer::offscreen` and after `release_world_mesh`; a shell loop sampled `VmHWM` every 0.2 s.
  CTRY's captured ticks 14-1333 once, with `CTRY.ALL` from the `vault-ctry` capture; LOCATION
  ticks 12-120 once, as a control.
- **Result**: CTRY, in KiB: scene built 9,400; renderer open 108,872 (+99,472, the device opened
  and the shapes, sprites and world uploaded); after the release 108,076; peak 147,396, so the
  frames add 38,524 over the renderer's open. LOCATION: scene built 308,008 RSS; renderer open
  703,048 RSS with `VmHWM` 766,252; after the release 444,440; peak 766,252, all of it reached by
  the time the renderer is open.
- **Verdict**: control. CTRY's peak is about 144 MiB: 9 MiB the scene, 97 MiB opening the device and
  uploading to it, 38 MiB the frames that follow; releasing its world mesh frees under 1 MiB (796 KiB).
  The one probed run's 144 MiB is 4 to 5 MiB above the unprobed runs' 139-140 MiB in the entry
  above, at another commit and with the probe's reads; that gap is not explained.
  LOCATION's 748 MiB peak matches the freed figure above.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

## 2026-11-20: the GPU's memory and byte-identity after freeing the world mesh

- **Question**: On the RTX 4070 Laptop, does freeing the world mesh's CPU copy after upload
  (`FilmScene::release_world_mesh`, #706) leave every reference film's render stores
  byte-identical, and what are LOCATION's and CTRY's peak working set and peak private bytes
  before and after it?
- **Method**:
  - `4c43baa` (#706's parent, `crates` `71486d7`) and `2ecbad1` (#706's merge, `crates`
    `a00c4e7`), each built with `mise run build-at` and checked out in its own detached
    worktree.
    The store schema gained a version after `2ecbad1`, so the current checkout's pipeline
    refuses the parent's `render.json`; each commit ran its own
    `mise run parity -- --no-build` on the GPU instead.
    All seven reference films, on the RTX 4070 Laptop GPU (no `VK_DRIVER_FILES`, no
    `--software-only`); every report named that adapter.
  - SHA-256 of each film's `frames.zst`, `layers.zst` and `palettes.zst` in both trees, and
    the seven summary lines.
  - Memory: the two binaries rendered headless with the parity flags (`--width 320 --height
    200 --viewport-rows 185`), LOCATION `--tick-range 12..=120` and CTRY `--tick-range
    14..=1333`, each film's capture archive and the FreeFlight `SIDATA`.
    Neither commit has `--report-memory` (#789 is later), so a PowerShell sampler polled
    `Get-Process` every 20 ms or so and recorded `PeakWorkingSet64` (peak working set),
    `PeakPagedMemorySize64` (peak private bytes), `WorkingSet64` and `PrivateMemorySize64`,
    plus `nvidia-smi`'s whole-GPU `memory.used`.
    Three runs each at each commit, one of them with no other render on the GPU.
    The base binary's first run after its build peaked at 640 MiB of working set, 41 MiB above
    its later runs (as #769 found), so the table quotes later runs, which repeated to 2 MiB.
    An 8,251-tick LOCATION render, the capture's whole span, also peaked at 598 MiB, so the
    film's length does not enter the peak.
- **Result**:
  - **Byte-identity**: all 21 store files are identical at the two commits, and the seven
    scores and every report's adapter are too.
    The hashes, each the same in both trees:

    ```text
    balloon   frames.zst    42daace74e416c13ca8cb8621d410b2bd09f95d8096947e744016181798f281a
    balloon   layers.zst    1fb0d2edc25efc047c2c4879f2b266eabf2ebd01f03583fe211ed6457533ddd1
    balloon   palettes.zst  d4da418953dae73bc97031b1e5449f2ba11296dc52e9026675287f11ec0b1c26
    bomb      frames.zst    ebbaa65199a84a50714146471391cc29f612cc1f1b12187e9c0e0d67ea7b5c80
    bomb      layers.zst    432cffe2cd0d41ebc1ef681386e17382043f569ea9a416b03dcd382cfad31d7b
    bomb      palettes.zst  d4da418953dae73bc97031b1e5449f2ba11296dc52e9026675287f11ec0b1c26
    ctry      frames.zst    59e31d27e001e4324e95e390bc734de20ae3f0d5c224ab19ab42bbcf0c23ea22
    ctry      layers.zst    77346028725f4bac0e9536cb200aff14ec4708d35fff46280322b6e743d29cb9
    ctry      palettes.zst  da5bfabfcd7e000e5d6b27ddf300c1517bdc8bfe1b8ff2efcd5a950489af82da
    intro     frames.zst    8aa0d70dc1a97a6ccf7bd662893a3b421825eb1ca7779b7e239deae07dbcf544
    intro     layers.zst    280942dc17e048ca476ba1faff05227392c67b4fca1e6feb0e6815769e504caf
    intro     palettes.zst  1916f08237b0d025de63975f3916722c017261b1d014bca08a804a9d8d0a3a4a
    land      frames.zst    af3130aa45b103fe19b6b317971b22ab1bb63d818c7cb4c54b78edc7c9f1c1fc
    land      layers.zst    6cb7fad6c8078b252b4aece7c7a0d88aaeb6fe9f03f9a84333abf4762a281d49
    land      palettes.zst  cba93762cd9089e939725610413daa61cb1b9e0de45ccfade5cbce1cd6f7c712
    location  frames.zst    d1c33a81eaf97e2c497e333beaf012ef7773fc95ed526174385b7ff7b3724090
    location  layers.zst    1b2cd64cb31f75d8da6904477bf68e88bea40fdd812146fa14b0bb6bd4e30233
    location  palettes.zst  f467d6646a04e66e0f6a14bba25def87d7434a29bba44d962dbc7dc9c41fd119
    traintnl  frames.zst    dfe94a2c92334b8a1db61742ef0bf7dff2de86f5738c573339829d2ee2c26e78
    traintnl  layers.zst    46605c2614d8f3a4b3cb86b7224e37c0d936782f82d448a68714e84436c29400
    traintnl  palettes.zst  8693c7227b8eee0d4b00710ea14781bb5c1526e27533fc9336e04d84a54e5cbb
    ```

  - **Memory**, in MiB, three runs each:

    | Film, ticks | Peak working set, `4c43baa` | Peak working set, `2ecbad1` | Peak private, `4c43baa` | Peak private, `2ecbad1` |
    |---|---|---|---|---|
    | LOCATION 12-120 | 598.3, 598.7, 598.7 | 597.7, 598.1, 599.5 | 1,301.3, 1,297.1, 1,302.2 | 1,289.0, 1,290.7, 1,288.5 |
    | CTRY 14-1333 | 161.5, 161.3, 161.3 | 160.4, 160.6, 160.1 | 343.0, 342.7, 342.8 | 341.4, 341.6, 340.5 |

  - The peak is reached during the world's upload, before `release_world_mesh` runs, so the
    release does not move it: LOCATION's peak working set is 598 to 599 MiB at both commits and
    its peak private 1,288 to 1,302 MiB, about 0.7 GiB above the working set on both.
    After the upload LOCATION's working set is about 485 MiB at `4c43baa` and about 227 MiB at
    `2ecbad1`, a 258 MiB drop that is the CPU mesh; CTRY's world is 20,044 vertices and its peak
    moves by about a MiB.
  - **VRAM** (`nvidia-smi`'s whole-GPU used memory, 3 MiB idle, sampled every 200 ms): a peak of
    522 MiB during LOCATION's render and 202 MiB during CTRY's, the same at both commits; the
    sampler's 200 ms interval can miss a shorter peak.
  - The 2026-11-16 pair, 942 MB working set and 1,443 MB private (#645), is not reproduced at
    `4c43baa`: this sampler reads 598 to 599 MiB and 1,297 to 1,302 MiB there, and `77a9a49`'s
    `--report-memory` peak was 603 MiB ([#769](../../2026-11/769_windows-render-memory/journal.md#2026-11-19---report-memory-on-windows-gpu-and-lavapipe)).
    The gap to 942 MB is not attributed.
- **Verdict**: control. The seven films' stores are byte-identical across #706, and on the GPU
  the release costs nothing at the peak, which happens during the upload, while returning the
  CPU mesh's working set afterwards; the renderer needs no change.
  The 0.7 GiB by which peak private bytes exceed the peak working set is consistent with the
  driver holding host-committed pages the release does not return; no per-allocation
  measurement was taken.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

