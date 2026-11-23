## 2026-11-22: decal pipeline switches greedy batching would leave

`[Bounded Observation]`

- **Question**: Over the whole `LOCATION` film (`12..=8262`) and Span B (`3680..=3979`), how many of the world's decal pipeline switches does batching consecutive decal slices with disjoint conservative screen boxes leave in place (#1000's probe)?
  The issue closes before any renderer change if most are left.
- **Method**:
  - `main` at `7bfc6cca` plus [`probe-decal-batch.patch`](probe-decal-batch.patch), CPU only: no renderer opens, no timing, no GPU or lavapipe render.
    `DBG_PROBE_DECAL_BATCH_FILE=<out>` makes `run_headless` call `probe_decal_batches` after the playback is built and return.
    The patch reuses [#920's CPU probe](../920_unbake-world-props/world-skip-and-vertex-probe.patch)'s `GpuModel::probe_cpu` and frame walk: per frame it sets the camera as `SceneRenderer::prepare` does (`projection_y_scale` from `--viewport-rows 185`) and calls `collect_world_meshes`, whose decal list is what `encode` draws one slice at a time before the sprite split.
  - A slice's box: its node's cull box (`node_bounds`, the box the walk culls on), its eight corners through `view_proj` to a `320 x 200` target, grown by 1 pixel each side for the outline (`pad 1`, the issue's conservative box).
    A node with no box, disc rim vertices under a non-default lens, or a corner with `w <= 1e-6` or `w - z < 0` (at or behind the near plane) takes the whole target, so it overlaps every slice.
  - Greedy batches in draw order: a slice joins the open batch if its box is disjoint from every member's, else the batch closes and the slice opens the next.
    A batch is one fill switch plus one outline switch.
    Today's cost is one fill switch plus one outline switch per slice (`2n`, as the issue counts).
    A second count gives a slice an outline only if its node holds a vertex `outlines_in_world` accepts (`n + outlined slices`); the two agree to `0.4%`, and the all-outline count is quoted.
    `pad 0` (boxes not grown) is a sensitivity run, not the conservative box.
  - Command: `DBG_PROBE_DECAL_BATCH_FILE=<out> stuntreel --headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range 12..=8262 --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --width 320 --height 200 --viewport-rows 185`, one release build (`mise exec -- cargo build --release -p stunt-cli`), run once, `3 s`; Span B is that run's ticks `3680..=3979`.
    The output has one line per frame (`8,251` of them); the sums and medians come from those lines.
  - Check against #920: ticks `3680..=3682` give `59` decal slices each, as #920's GPU-side print did, and Span B's median is `327`, as the issue quotes.
- **Result**:
  - Pipeline switches, today and after greedy batching with `pad 1`:

    | Scope | Frames | Decal slices (median a frame) | Switches today | Switches batched | Left in place | Removed |
    |---|---|---|---|---|---|---|
    | Whole `LOCATION` film | 8,251 | 12 | 421,326 | 228,160 | 54.2% | 45.8% |
    | Span B | 300 | 327 | 117,228 | 53,728 | 45.8% | 54.2% |
    | Whole film outside Span B | 7,951 | | 304,098 | 174,432 | 57.4% | 42.6% |

    Whole-film slices: `210,663`, in `114,080` batches, `1.85` slices a batch; Span B: `58,614` slices in `26,864` batches, `2.18` a batch.
    Per-frame medians of the share left: `60.0%` (whole film), `46.2%` (Span B).
    Span B holds `27.8%` of the film's switches in `3.6%` of its frames; `241` frames have `100` or more decal slices.
  - Sensitivity (`pad 0`, not conservative): whole film `183,780` switches left of `421,326` (`43.6%`); Span B `34,448` of `117,228` (`29.4%`).
  - Whole-target boxes (a node with no box or a corner at or behind the near plane): `2,706` of `210,663` whole-film slices (`1.3%`), a median `1` a frame on Span B.
  - Against the ceiling the issue names: [#920's grouping probe](../920_unbake-world-props/journal.md#2026-11-22-what-the-worlds-base-and-decal-draws-cost-on-lavapipe) `g` cut the whole film's loop `7.7%` (2 rounds), with about every decal switch gone.
    If the saving were proportional to the switches removed (not measured), batching's `45.8%` would give at most `3.5%` (`4.3%` at `pad 0`), under the `5%` gate.
- **Verdict**: batching leaves `54.2%` of the whole film's decal pipeline switches in place with the conservative box, most of them, so the issue closes by its own rule; its ceiling, `7.7%` times the `45.8%` removed, is under the `5%` gate unless a removed switch costs more than the proportional share.
  Span B leans the other way (`45.8%` left, `54.2%` removed); the gate is the whole film's.
  The margin is `4.2` points over half, and the `pad 0` run falls under half (`43.6%` left), so the verdict rests on the conservative box and on the ceiling, not on the count alone.
  No timing was taken: the proportional bound is an inference from #920's two-round whole-film figure, not a measurement.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3, § 6 and Ruled out.
