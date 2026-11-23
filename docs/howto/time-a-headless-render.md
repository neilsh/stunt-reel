# Time a headless render

`--report-timing` makes a headless `stuntreel` render print, to stderr, how long its start-up phases and its frame loop took.
It sits beside `--report-memory` ([Measure a headless render's memory](measure-a-renders-memory.md)) and, like it, reads a clock and writes no file.
On the synthetic `synthetic_timeline.flm`, the render store was byte-identical with the flag on and off (a `diff -r` of two `--out-dir` renders on a GPU adapter, 2026-11-23, and `report_timing_prints_each_phase_and_leaves_the_store_alone` in [`timing_test.rs`](../../crates/stunt-cli/tests/it/timing_test.rs) on the software adapter, which this machine lacked).
A time read from one run on a busy machine is a smoke check, not a measurement.

## 1. Run it

```bash
target/release/stuntreel --headless "<film>.FLM" --all "<film>.ALL" --tick-range 12..=120 \
    --software-only --out-dir build/scratch/timed --report-timing
```

The flag needs a headless render (`--headless`, `-o`, `--out-dir` or `--video`) and goes with any film and any of its flags.
The lines are printed together, at the end of a successful run, so a run that fails prints none.

## 2. The output format

One line per phase, on stderr, in this order:

```text
[stuntreel] timing scene_build 1234.567 ms
[stuntreel] timing world_build 345.006 ms
[stuntreel] timing renderer_open 900.000 ms
[stuntreel] timing world_upload 700.250 ms
[stuntreel] timing shape_uploads 40.000 ms
[stuntreel] timing loop 12000.000 ms
```

Each line is `[stuntreel] timing <phase> <milliseconds> ms`, the milliseconds a decimal with three places.
`PHASES` in [`timing_report.rs`](../../crates/stunt-cli/src/timing_report.rs) owns the names and their order; a runner that parses the lines can rely on both.

| Phase | What it times |
|---|---|
| `scene_build` | `build_timed_scene`: reading the film, archive and scenery files, decoding the shapes, building the world and attaching the credits font. |
| `world_build` | Part of `scene_build`: `build_world` alone. Zero for a scene with no archive or game tree. |
| `renderer_open` | `Renderer::offscreen`: the adapter, the device, the pipelines, then the uploads below. |
| `world_upload` | Part of `renderer_open`: the world mesh, its prop runs and its placement marks. Zero with no world. |
| `shape_uploads` | Part of `renderer_open`: every shape and sprite image. |
| `loop` | From the first sample's frame build and submit through `finish` and the last page write, as the throwaway loop timers measured it. For a single `-o` PNG, the one `draw`. |

The upload phases are CPU time in the upload calls: the device may finish copying afterwards, and that time falls in `loop`.
A `--workers N` run passes the flag to its child renders (`args` in [`workers.rs`](../../crates/stunt-cli/src/workers.rs)), and each child prints its own lines.
