# Journal

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
    Three runs each at each commit, the third on an idle GPU; the first two runs of each cell
    are in `build/scratch/707/memory2.csv` and the third in `build/scratch/707/vram2.csv`
    (LOCATION) and `build/scratch/707/vram3-ctry.csv` (CTRY).
    The base binary's first run after its build peaked at 640 MiB of working set, 41 MiB above
    its later runs (as #769 found), so the table quotes later runs.
    `build/scratch/707/memory.csv` is an earlier batch, not quoted in these ranges; its head
    peak private readings are 1,288.0 and 1,288.9 MiB (about 1 MiB under the lowest quoted) and
    its base readings 1,318.9 MiB (the first run after the build) and 1,302.6 MiB.
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
    | LOCATION 12-120 | 598.3, 598.7, 597.5 | 597.7, 598.1, 598.7 | 1,301.3, 1,297.1, 1,303.2 | 1,289.0, 1,290.7, 1,289.6 |
    | CTRY 14-1333 | 161.5, 161.3, 161.2 | 160.4, 160.6, 160.0 | 343.0, 342.7, 343.0 | 341.4, 341.6, 341.2 |

    The first two values of each cell are in `build/scratch/707/memory2.csv`; the third is
    `vram4-base-location` and `vram4-head-location` in `build/scratch/707/vram2.csv`, and
    `vram3-base-ctry` and `vram3-head-ctry` in `build/scratch/707/vram3-ctry.csv`.

  - Equal peaks at both commits put the peak before the release: LOCATION's peak working set is
    about 598 MiB at both, and its peak private falls about 10 MiB, from 1,297-1,303 to
    1,289-1,291 MiB, about 0.7 GiB above the working set on both.
    After the upload LOCATION's working set is 483.1 and 482.3 MiB at `4c43baa` and 227.5 and
    226.2 MiB at `2ecbad1` (the median of the samples between the upload peak and the teardown
    drop, in `build/scratch/707/mem-logs/<run>/samples.csv`), a drop of about 256 MiB, about the
    CPU mesh's 253 MiB; CTRY's world is 20,044 vertices and its peak moves by about a MiB.
  - **VRAM** (`nvidia-smi`'s whole-GPU used memory, idle at 0 MiB, sampled every 200 ms): 520
    MiB during LOCATION's render and 200 MiB during CTRY's, the same at both commits, in
    `build/scratch/707/vram2.csv` and `vram3-ctry.csv`; the sampler's 200 ms interval can miss a
    shorter peak.
  - The 2026-11-16 pair, 942 MB working set and 1,443 MB private (#645), is not reproduced at
    `4c43baa`: this sampler reads about 598 MiB and 1,297 to 1,303 MiB there, and `77a9a49`'s
    `--report-memory` peak was 603 MiB ([#769](../769_windows-render-memory/journal.md#2026-11-19---report-memory-on-windows-gpu-and-lavapipe)).
    The gap to 942 MB is not attributed.
- **Verdict**: control. The seven films' stores are byte-identical across #706; on the GPU the
  release does not move the peak working set, which is reached before it runs, while peak
  private falls about 10 MiB and the working set afterwards drops by about 256 MiB; the
  renderer needs no change.
  The 0.7 GiB by which peak private bytes exceed the peak working set is consistent with the
  driver holding host-committed pages the release does not return; no per-allocation
  measurement was taken.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).
