## 2026-11-22: decal pipeline switches greedy batching would leave

`[Bounded Observation]`

- **Question**: Over the whole `LOCATION` film (`12..=8262`) and Span B (`3680..=3979`), how many of the world's decal pipeline switches does batching consecutive decal slices with disjoint conservative screen boxes leave in place (#1000's probe)?
  The issue's rule closes it if batching "leaves most switches in place", and names no scope.
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
    If the saving were proportional to the switches removed (not measured), batching's `45.8%` would give about `3.5%` (`4.3%` at `pad 0`).
    A removed switch does not cost the same everywhere: #920's grouping saved `955 ms` on Span B and `1,122.5 ms` elsewhere (`2,077.5 ms` of the whole film's `27,062.5 ms`, minus Span B's), which is about `8.1 µs` a switch on Span B (`955 / 117,228`) and `3.7 µs` elsewhere (`1,122.5 / 304,098`).
    Weighting each span's removed share by its own saving, `0.542 x 955 + 0.426 x 1,122.5 = 996 ms`, gives about `3.7%` of `27,062.5 ms` (`4.6%` at `pad 0`, `0.706 x 955 + 0.509 x 1,122.5 = 1,246 ms`); both are inferences, since Span B's and the whole film's runs are separate, and both are under the `5%` gate.
- **Verdict**: not settled; whether #1000 closes is the owner's ruling on which scope its rule ("if batching leaves most switches in place, close this issue") names.
  With the conservative box the whole film leaves `54.2%` of its decal pipeline switches in place (most), and Span B leaves `45.8%` (not most), so the two scopes give opposite answers.
  The ceiling is under the `5%` gate at both: `3.5%` if proportional, `3.7%` weighted by span (inferences); but at `pad 0` the whole film leaves `43.6%` (not most) and Span B `29.4%`, so the count alone does not decide it.
  No timing was taken: the bounds are inferences from #920's two-round whole-film figure and its Span B figure, not measurements.
  The `outcome` stays blank until the owner rules; phase B (a renderer change for Span B) follows only if they read the rule per span.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3, § 6 and Open questions.

## 2026-11-23: the owner's ruling on scope

`[Bounded Observation]`

- **Question**: Does #1000's probe rule, "if batching leaves most switches in place, close this issue", read at the whole `LOCATION` film or per span?
  The entry above left it to the owner: the whole film leaves `54.2%` of the decal pipeline switches in place, Span B `45.8%`.
- **Ruling** (the owner's comment on #1000, 2026-11-23, `mise run now` 2026-11-23T09:46+00:00):
  - The rule reads at the gate's scope, the whole film, where batching leaves `54.2%` (`228,160` of `421,326`): #1000 closes with no renderer change, and phase B's implementation is dropped.
  - The ceiling leads the note: #920's `7.7%` whole-film grouping saving times the `45.8%` of switches removed is about `3.5%` of the loop (`7.7 x 0.458 = 3.53`), about `3.7%` span-weighted (`996 ms` of `27,062.5 ms`), under the `5%` gate at either scope; inferences, not timings.
    The `7.7%` is not re-measured.
  - Pad 0 (`4.3%` proportional, `4.6%` span-weighted) is outside the issue's design, whose boxes must be conservative, so it does not trigger the one-point rule.
  - Span B, where batching removes `54.2%` of the switches, is context only; nothing is filed for it.
  - The note names one alternative in a sentence: an order buffer that makes decal draw order commutative could reach most of the `7.7%` ceiling, but needs a second order target beside the world's depth; not probed.
  - #999's design note is to cite this close.
- **Verdict**: ruled out; no timing was taken, so the verdict rests on the count above and #920's figures.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6 and Ruled out.
