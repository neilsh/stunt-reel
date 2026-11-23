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
    Check, on every frame: the probe's slices equal `collect_world_meshes`'s, slice for slice and in order (`walk_mismatches 0` on every film, in [`probe/probe.log`](probe/probe.log)).
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
