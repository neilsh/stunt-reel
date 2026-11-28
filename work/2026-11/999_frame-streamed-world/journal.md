## 2026-11-23: world stream sizes a frame on the seven reference films

- **Question**: How many vertices, indices and outline indices does the world walk emit at most in one frame of each reference film, the sizes a frame-streamed world's buffers would need (#999's "Probe first")?
  CPU only: no device, no render, no timing.
- **Method**:
  - `main` at `eabff61a` plus [`world-stream-probe.patch`](world-stream-probe.patch), one release build (`cargo build --release -p stunt-cli`).
    With `DBG_PROBE_WORLD_STREAM_FILE=<csv>` set, `run_headless` returns before the renderer opens, after `probe_world_stream` has walked the world on every sampled frame's camera.
  - `GpuModel::probe_plan` runs the upload's own planning on the world IR, as `SceneRenderer::new` asks for it: `plan_upload` with the 256 MiB buffer limit of `downlevel_defaults` (the probe refuses a plan of more than one chunk), then `plan_edges` with `outlines_in_world` and `WorldPlacements::marks`.
    It builds the same `GpuNode` arena `GpuModel::upload` builds, with no buffers.
  - Each frame builds the camera as `Renderer` does for an offscreen target with `--viewport-rows 185` (`projection_y_scale = 200 / 185`), then the world's `view_proj` and LOD view as `SceneRenderer::prepare` does.
    `probe_world_walk` repeats `VisibleWalk::split`'s two walks, tagging the ground slices with their nodes too, in the order a stream would hold them: ground (forward walk), base (backward walk), decal (forward walk).
    Check, on every frame: the probe's slices equal `collect_world_meshes`'s, slice for slice and in order (`walk_mismatches 0` on every film, in [`probe/probe.txt`](probe/probe.txt)).
  - Per frame and per list it sums the slices, the vertices (each emitted node's whole vertex window, `NodeKind::Mesh`'s `vertex_count`, which a stream would copy), the indices (`index_count`) and the outline indices (`edge_count`, two an edge).
    Every mesh node's indices lie inside its own window (`indices_outside_window 0` on every film), and each node has one slice, so a node's vertices are copied once a frame.
    `run_pieces` counts the prop runs (`World::prop_runs`) the emitted windows overlap, each clipped to its window, which a per-frame runs table would hold; `run_merged` merges a piece into the one before it when both have the same shape and nothing lies between them in the stream.
    A frame whose `SceneFrame::world` is false writes zeros (none did).
  - Each film is the parity render's own command (`parity_pipeline.render_film`: the captured tick range, `--width 320 --height 200 --viewport-rows 185`), driven by [`probe_world_stream.py`](probe_world_stream.py) with the data root `E:\git\stunt-reel.data`; one run each, on the owner's laptop.
- **Result**: raw rows in [`probe/`](probe/) (`<film>.csv`, one row a frame), the per-film figures in [`probe/summary.csv`](probe/summary.csv).
  - The probe's world totals for `LOCATION` (`228,159` nodes, `6,704,202` vertices, `7,493,034` indices, `12,861,070` outline indices, `31,441` runs) and `INTRO` (`128,768`, `819,265`, `1,002,423`, `1,513,630`, `9,815`) equal #920's byte count ([what un-baking would keep baked](../920_unbake-world-props/journal.md#2026-11-22-what-un-baking-would-keep-baked)).
    Its `LOCATION` base and decal vertices a frame, mean `4,297.2`, median `1,000`, max `58,332`, equal #920's step 2 probe's mean and median ([vertices a per-placement frustum test would remove](../920_unbake-world-props/journal.md#2026-11-22-vertices-a-per-placement-frustum-test-would-remove)) and the issue's "about 58k at most".
  - Per frame, ground, base and decal together (each film's maximum, the tick it falls on, and the mean over the film's frames):

    | Film | Frames | Max vertices | Max indices | Max outline indices | Max slices | Mean vertices | Mean indices | Mean outline indices |
    |---|---|---|---|---|---|---|---|---|
    | `CTRY` | 1,320 | 9,485 (83) | 7,200 (1063) | 8,556 (1063) | 143 | 3,123.4 | 3,621.5 | 3,218.3 |
    | `INTRO` | 3,807 | 75,576 (3635) | 76,008 (3635) | 149,956 (3635) | 138 | 8,207.3 | 8,359.3 | 14,459.0 |
    | `LAND` | 1,123 | 14,913 (218) | 8,271 (527) | 12,730 (218) | 237 | 5,973.7 | 4,399.2 | 4,927.9 |
    | `BALLOON` | 1,179 | 5,493 (982) | 4,383 (982) | 6,382 (982) | 62 | 1,113.1 | 1,389.5 | 895.7 |
    | `TRAINTNL` | 1,222 | 15,566 (101) | 7,986 (101) | 10,680 (101) | 290 | 4,093.2 | 3,568.9 | 2,927.3 |
    | `BOMB` | 3,719 | 23,753 (12) | 25,104 (12) | 45,608 (12) | 455 | 9,150.9 | 10,164.3 | 16,526.2 |
    | `LOCATION` | 8,251 | 60,838 (5151) | 62,712 (5151) | 116,832 (5151) | 990 | 7,013.8 | 8,140.3 | 8,812.3 |
    | All seven | 20,621 | 75,576 (`INTRO` 3635) | 76,008 (`INTRO` 3635) | 149,956 (`INTRO` 3635) | 990 | 6,803.4 | 7,395.9 | 9,875.0 |

  - The ground slices alone peak at `14,935` vertices (`TRAINTNL` 101), `10,149` indices (`LOCATION` 5254) and `13,046` outline indices (`LOCATION` 2397); the base and decal slices alone at `75,065`, `75,111` and `149,502` (`INTRO` 3635).
  - A per-frame runs table would hold at most `987` pieces (`LOCATION` 3824), or `399` merged (`LOCATION` 2904); `LOCATION`'s whole-world table has `31,441` runs.
  - Bytes, by the sizes in `GpuChunk::upload` (vertex `28` B, index `4` B, outline index `4` B), from the per-frame rows ([`summary.csv`](probe/summary.csv) holds the counts):
    the largest frame of all seven is `INTRO` 3635 at `3,019,984` B (`2.88` MiB; `3.74` MiB with the `12` B apex stream kept), and every buffer's maximum falls on that frame, so buffers sized each to its own maximum also total `2.88` MiB.
    `LOCATION`'s largest frame is `2,421,640` B (`2.31` MiB, tick 5151), its mean `264,195.7` B a frame, and the whole film's frames together `2,078.9` MiB, against the `333.75` MiB of buffers the baked world uploads once (#920's count).
- **Verdict**: control, recorded only; the issue sets no gate on the probe.
  A stream sized to the largest frame of the seven films needs about `75.6k` vertices, `76.0k` indices and `150.0k` outline indices, `2.88` MiB, about `0.9%` of `LOCATION`'s `333.75` MiB of world buffers.
  The maxima are of these seven films' captured tick ranges at `320 x 200` with `185` viewport rows; another film, lens or viewport can emit more, so a growth policy is still needed.
  Nothing here times a frame's copy or its `write_buffer`; on `LOCATION` it would move about `0.26` MB a frame, about `2.0` GiB over the film.
  `[Bounded Observation]`: one CPU run per film, one machine, the counts only.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3.

## 2026-11-28: stage B, the world drawn from the stream, stores and memory on cloud lavapipe

- **Question**: with `STUNT_WORLD_STREAM=1` (`RenderOptions::world_stream`), does the scene renderer draw stores byte-identical to the baked world on the seven reference films, and what does it do to peak memory (#1092's two acceptance items)?
- **Built**: layer 1 (#1214) carries each streamed vertex's shape word in the apex section, restages the renderer's slice lists in place, plans the world without device buffers (`GpuModel::plan_outlined`) and adds `StreamBuffers`; layer 2 draws from them.
  With the switch on the world has no device buffer and the renderer keeps an owned copy of the mesh (`StreamSource`, `ir.vertices`, `ir.indices`, the outline list, the prop runs and the rank spheres; no apex copy, since each world vertex's own apex is computed per window from those spheres by `own_apexes_of`); the CLI frees the scene's copy as before.
- **How**:
  - Stores: [`stream_store_check.py`](stream_store_check.py) renders each film twice with one release binary, `STUNT_WORLD_STREAM` unset then `=1`, through `parity_pipeline.render_film`, and hashes `frames`, `layers`, `palettes` and `shapes`; it fails when a render with the switch on lacks the `[stuntreel] world stream: on` line or one with it unset has it, and when any render reports a fallback.
    Cloud lavapipe (Mesa 25.2.8 from `mesa-vulkan-drivers`), on the branch rebased onto main `a243102` (#1101 merged), `--software-only`, data from `mise run cloud-assets -- fetch --replace-unmarked`, `game-builds` and `superset-all`, one process a film.
  - Memory: [`stream_memory_check.py`](stream_memory_check.py), `LOCATION` ticks `12..=120` with `--report-memory`, three runs each, off and on, interleaved.
- **Result**:
  - Stores, [`stream-stores.csv`](stream-stores.csv): all four planes' hashes are identical between off and on on `CTRY`, `INTRO`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB` and `LOCATION`, on cloud lavapipe.
    The Windows lavapipe and RTX 4070 runs are not done (they need the owner's machine); the PR says so.
  - Peak memory, [`stream-memory.csv`](stream-memory.csv), MiB of resident memory on cloud lavapipe:

    | Variant | Scene built | Renderer opened | Mesh released | Frames rendered | Peak |
    |---|---|---|---|---|---|
    | off | 347.2 to 351.3 | 917.6 to 920.7 | 631.2 to 634.3 | 732.9 to 736.1 | 1069.3 to 1072.5 |
    | on | 347.3 to 351.4 | 789.7 to 792.6 | 503.3 to 506.1 | 527.4 to 530.2 | 789.4 to 792.4 |

    The peak is lower with the stream on by `280.5`, `277.3` and `280.1` MiB in runs 0, 1 and 2.
    On lavapipe a "device" buffer is host memory, which is why dropping the world's device buffers shows in resident memory; an RTX 4070's device memory is not in the process's resident set, so its figure is for the Legion run.
- **Verdict**: stores identical on cloud lavapipe for the seven films, one render each per variant; peak memory lower on cloud lavapipe in three of three pairs, by `277` to `281` MiB; `[Bounded Observation]`, one machine, one day.
  Both adapters on Windows remain.
  Not timed: stage C owns the loop gate.
- **Lives in**: this entry; `lavapipe-render-time.md` § 6 is written by stage C.


## 2026-11-28 Stage B: Windows lavapipe and RTX 4070 stores and memory

- **Question**: do the stores match, and what does the stream do to peak memory, on the Legion's Windows lavapipe (mesa-dist-win 25.2.8) and RTX 4070 (#1092's remaining item)?
- **Built**: the release `stuntreel.exe` at main `287fc28a` (#1215), the machine idle (about 2 % CPU) and the loop not timed.
- **How**: [`stream_store_check.py`](stream_store_check.py) and [`stream_memory_check.py`](stream_memory_check.py) with `--adapter lavapipe --adapter gpu`, run through a one-off wrapper that skips the reference capture's pinned-hash check.
  The wrapper was needed because four local captures (`ctry`, `land`, `bomb`, `location`) pre-date the pins #1165 moved and `cloud-assets fetch` has no credentials here; `ctry` was recaptured locally (hash differs from the pin) and the other three are the older captures.
  Both variants of a pair read the same capture with the same binary, so the pair compares like with like; the stores are not compared to the pinned capture.
- **Result**:
  - Stores, [`stream-stores-win.csv`](stream-stores-win.csv): off and on are identical in all four planes on the seven films, on both adapters (14 of 14 pairs).
  - Peak memory, [`stream-memory-win.csv`](stream-memory-win.csv), MiB of resident memory, three runs each:

    | Adapter | Variant | Renderer opened | Frames rendered | Peak |
    |---|---|---|---|---|
    | lavapipe | off | 868.3 to 869.0 | 675.8 to 676.0 | 1020.9 to 1021.5 |
    | lavapipe | on | 740.3 to 741.3 | 469.9 to 471.2 | 740.8 to 741.9 |
    | RTX 4070 | off | 531.0 to 531.3 | 245.4 to 245.6 | 825.1 to 825.3 |
    | RTX 4070 | on | 814.4 to 815.3 | 529.8 to 530.0 | 814.4 to 815.3 |

    The peak is lower by about `280` MiB on lavapipe and by about `11` MiB on the RTX 4070, where the stream's host-side copy of the mesh raises the resident set after the renderer opens by about `283` MiB; the stages' peaks (`825` off, `815` on) are not explained by the four stage readings, which this run did not look into.
- **Verdict**: stores identical on all seven films on Windows lavapipe and the RTX 4070; peak memory lower on both, in three of three pairs; `[Bounded Observation]`, one machine, one day, the reference captures not at their pins.


## 2026-11-28: stage C, the stream as the only world path, loop, memory and stores

- **Question**: with the baked world upload deleted and the stream the only world path (#1093), is the whole `LOCATION` film's lavapipe loop no slower than base within 2%, is peak memory no higher on either adapter, and are the stores byte-identical on the seven reference films on both?
- **Built**: `181fabc9` deletes `GpuModel::from_ir_outlined` and its device buffers and staging copies, `STUNT_WORLD_STREAM` and its fallback, and buffer splitting (`plan_upload`, `flush_run`, `ChunkPlan`, `GpuChunk::vertex_ranges`, `GpuMeshSlice::chunk` and `vertex_offset`, the split half of `plan_edges`); every shape is one buffer set and the world is planned without one (`GpuModel::plan_outlined`).
  `marks`, `cut` and `cut_out` stay: cutting a slice at a placement's span end needs the outline offset there, which only the plan computes (#1228).
  Base is `main` at `459f46d2`; both are release binaries from `mise run build-at`, on the Legion (Ryzen 7 7745HX, RTX 4070 Laptop), mesa-dist-win 25.2.8.
- **How**:
  - Pre-check, not the gate: `459f46d2` against itself with `STUNT_WORLD_STREAM=1`, whole film, 4 pairs ([`stage-c-precheck-lavapipe.csv`](stage-c-precheck-lavapipe.csv)); it stopped on the load check after its last run.
  - Loop: `mise run ab -- --variant "base binary=..." --variant "stream binary=..." --span 12..=8262 --rounds 4 --order alternate --max-load 0.15`, on lavapipe ([`stage-c-loop-lavapipe-2.csv`](stage-c-loop-lavapipe-2.csv), [summary](stage-c-loop-lavapipe-2-summary.md)) then the RTX 4070 ([`stage-c-loop-gpu.csv`](stage-c-loop-gpu.csv), [summary](stage-c-loop-gpu-summary.md)).
    The first lavapipe run at the default 10% load bar stopped after one run at `15%` other load ([`stage-c-loop-lavapipe.csv`](stage-c-loop-lavapipe.csv)): an orphaned `find / -maxdepth 6` of another session kept about one core busy for more than 26 minutes.
    The 15% bar is the one the owner allowed for `#1018`'s completed A/A; every kept lavapipe run read `9%..10%` other load and every RTX 4070 run `8%..11%`, and the 2% gate is unchanged.
  - Memory: [`stage_c_memory_check.py`](stage_c_memory_check.py), `LOCATION` ticks `12..=120` with `--report-memory`, three runs each, the binaries interleaved, both adapters ([`stage-c-memory.csv`](stage-c-memory.csv)).
  - Stores: [`stage_c_store_check.py`](stage_c_store_check.py) renders each reference film with each binary through `parity_pipeline.render_film` on both adapters and hashes the four planes ([`stage-c-stores.csv`](stage-c-stores.csv)).
    `ctry`, `land`, `bomb` and `location` captures here are not at their `references.toml` pins, as in stage B's Windows run, so those films render against their current captures; both binaries of a film read the same capture.
- **Result**:
  - Lavapipe loop: base `24051.9, 24321.8, 24145.9, 24184.1` ms, stream `23679.7, 24167.8, 24227.1, 23969.2`; median `24165` to `24068.5` ms (`-0.4%`), stream faster in 3 of 4 pairs, stores the same.
    The pre-check (one binary, switch off then on) gave `-1.7%`, faster in 3 of 4.
  - RTX 4070 loop: base `9346.1, 9429.2, 9158.4, 9278` ms, stream `10525.2, 10651, 10677.9, 10726`; median `9312` to `10664.4` ms (`+14.5%`), slower in all 4 pairs, ranges disjoint; not traced.
  - Peak memory, MiB:

    | Adapter | Binary | Renderer opened | Mesh released | Frames rendered | Peak |
    |---|---|---|---|---|---|
    | lavapipe | base | 872.8 to 873.6 | 578.3 to 579.1 | 680.8 to 681.0 | 1025.3 to 1026.2 |
    | lavapipe | stage C | 738.4 to 739.5 | 441.8 to 444.8 | 468.5 to 469.0 | 738.5 to 739.7 |
    | RTX 4070 | base | 533.9 to 534.7 | 237.1 to 237.3 | 248.5 to 248.9 | 827.9 to 828.7 |
    | RTX 4070 | stage C | 811.3 to 811.6 | 513.3 to 514.1 | 523.0 to 526.2 | 811.4 to 811.7 |

    The peak is lower in every pair: by `287.4`, `285.6` and `287.0` MiB on lavapipe and `17.3`, `16.3` and `16.5` MiB on the RTX 4070.
  - Stores: identical in all four planes on all seven films on both adapters (14 of 14 pairs).
- **Verdict**: the lavapipe loop gate passes (`-0.4%` against a bar of `+2%`), peak memory is lower on both adapters, and the stores are identical, so stage C lands; `[Bounded Observation]`, one machine, one run of each gate, four captures not at their pins.
  The RTX 4070's `+14.5%` does not gate, as the issue sets it; it is reported to the owner; that the per-frame `write_buffer`, which on a discrete GPU crosses the bus each frame, costs it is `[Hypothesis]`, not tested (#1227).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 1 and [`lavapipe-render-workers.md`](../../../research/parity/lavapipe-render-workers.md) section 3.
