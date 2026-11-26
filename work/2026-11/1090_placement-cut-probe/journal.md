## 2026-11-26: placements cut out of the shared slices on the seven reference films

`[Bounded Observation]`

- **Question**: On the five reference films #920 did not check (`CTRY`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`), does any placement lie in the world's shared `WORLD_BASE` or `WORLD_DECAL` slice, so that the renderer cuts it out of them (#999's design note section 6, open call 8)?
- **What #920 probed**: on `LOCATION` and `INTRO` only, for each placement record with mesh spans, whether its `MeshSpans` hold a base or decal index in the `WORLD_BASE` or `WORLD_DECAL` run ([vertices a per-placement frustum test would remove](../920_unbake-world-props/journal.md#2026-11-22-vertices-a-per-placement-frustum-test-would-remove): `35,479` of `56,585` records on `LOCATION` have spans, none in either run; `INTRO` `10,723` of `26,386`).
  #999's design note repeats it ("`#920` found no placement with geometry there on `LOCATION` or `INTRO`, and the other five films were not checked").
- **Method**:
  - `main` at `25eb9586` plus [`world-cuts-probe.patch`](world-cuts-probe.patch), CPU only: `DBG_PROBE_WORLD_CUTS=1` makes `run_headless` call `probe_world_cuts` (in `scene_renderer.rs`) right after the scene is built, and return before any renderer opens.
    It builds `WorldPlacements::new(world)` (what `SceneRenderer` reads to cut slices) and counts, over `spans`, the records with mesh spans, those with a non-empty `base` and `decal` span (and how many lie inside the `WORLD_BASE` and `WORLD_DECAL` runs), and those with nodes of their own.
    It is the same count as #920's over the same `MeshSpans`, not the same patch: #920's patch also walked frames and tested placement boxes, which a zero count makes moot.
  - Command: [`probe_world_cuts.py`](probe_world_cuts.py), `mise exec -- uv run python work/2026-11/1090_placement-cut-probe/probe_world_cuts.py <data root> <out> [film ...]`, which runs the release binary built with the patch (`mise exec -- uv run python -c "from stunt_reel import parity_pipeline as p; p.build_release()"`) on each film as `parity_pipeline.render_film` does (`stuntreel --headless <FILM>.FLM --all <FILM>.ALL --tick-range <captured range> --sidata SIDATA --out-dir render --width 320 --height 200 --viewport-rows 185`), all seven films, the two #920 checked as a control.
  - Output: [`probe.txt`](probe.txt), whitespace collapsed.
- **Result**:

  | Film | Captured tick range (does not bound the count) | Nodes | Records | With mesh spans | Non-empty base span | Non-empty decal span | With own nodes |
  |---|---|---|---|---|---|---|---|
  | `CTRY` | `14..=1333` | 1,040 | 316 | 306 | 0 | 0 | 306 |
  | `INTRO` | `12..=3818` | 128,772 | 26,386 | 10,723 | 0 | 0 | 10,723 |
  | `LAND` | `12..=1134` | 2,724 | 845 | 834 | 0 | 0 | 834 |
  | `BALLOON` | `12..=1190` | 9,930 | 8,983 | 1,589 | 0 | 0 | 1,589 |
  | `TRAINTNL` | `12..=1233` | 4,291 | 1,049 | 1,049 | 0 | 0 | 1,049 |
  | `BOMB` | `12..=3730` | 6,091 | 1,158 | 970 | 0 | 0 | 970 |
  | `LOCATION` | `12..=8262` | 228,194 | 56,585 | 35,481 | 0 | 0 | 35,481 |

  - Every film's `WORLD_BASE` run is indices `0..342` and its `WORLD_DECAL` run `342..360`, as #920 found on `LOCATION` and `INTRO`; no span lies in either (`base_in_run` and `decal_in_run` are `0` too).
  - The control reproduces #920 on `INTRO` (records `26,386`, with spans `10,723`, none in a run) and on `LOCATION` (records `56,585`, none in a run).
    Its totals differ a little from #920's and #999's: `INTRO` `128,772` nodes and `819,745` vertices (against `128,768` and `819,265`), `LOCATION` `228,194` nodes and `35,481` records with spans (against `228,159` and `35,479`).
    `[Hypothesis]` the OP_BLOCK cube change (#1032, `1e1d5680`), merged after #999's probe tree `eabff61a`, adds them; not isolated (the probe was not run on the older tree).
  - The probe's records are the placements the world build keeps (a placement under an `SP_1NODE` pruned as far from every camera eye is absent, as in the world mesh), counted once a film, not per tick.
- **Verdict**: no placement of any of the seven reference films lies in the shared base or decal slice, so none is cut out of them; the five films agree with #920's two.
  For #999's design note: its byte-identical stream test over the seven films needs no span-per-placement range for the shared slices, and the builder's range for such a placement would be exercised by none of them (only by a synthetic fixture, if it is built).
  The design is not decided here: open call 8 stays the owner's.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 3 and its Ruled out (#920's entry).
