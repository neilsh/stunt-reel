# Time a headless render

`--report-timing` makes a headless `stuntreel` render print, to stderr, how long its start-up phases and its frame loop took.
It sits beside `--report-memory` ([Measure a headless render's memory](measure-a-renders-memory.md)) and, like it, writes no file; it reads the clock where `--report-memory` reads resident memory.
On the synthetic `synthetic_timeline.flm`, the render store was byte-identical with the flag on and off (a `diff -r` of two `--out-dir` renders on a GPU adapter, 2026-11-23, and `report_timing_prints_each_phase_and_leaves_the_store_alone` in [`timing_test.rs`](../../crates/stunt-cli/tests/it/timing_test.rs), which runs on the software adapter and skips when none is installed, unless `STUNT_REQUIRE_GPU=1`).
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

## 4. Time variants against each other

`mise run ab` ([`ab.py`](../../python/scripts/ab.py), [`ab_timing.py`](../../python/stunt_reel/ab_timing.py)) runs `--report-timing` renders of two or more variants in interleaved rounds, so a timing issue's gate names its rounds and order rather than restating a runner.
A variant is a name, optionally its own binary, and the environment variables it sets; the first is the baseline.
Build every binary first: the runner runs them as they are.

```bash
mise run ab -- --out work/2026-11/<issue>_<slug> --name span-b     --variant base --variant "skip STUNT_PROBE_SKIP_WORLD=1"     --span 3680..=3979 --adapter lavapipe --rounds 4 --order alternate
mise run ab -- --out work/2026-11/<issue>_<slug> --name two-builds     --variant "old binary=build/old.exe" --variant "new binary=build/new.exe"
```

* **Cells.**
  Each `--span` runs on each `--adapter` (`lavapipe`, the default, or `gpu`).
  Lavapipe sets `VK_DRIVER_FILES` to `--icd` (default `<data root>/tools/mesa-25.2.8/x64/lvp_icd.x86_64.json`, [Render on lavapipe beside a GPU](render-on-lavapipe.md)) and passes `--software-only`; the GPU leaves both off.
  A run whose `render.json` names the other adapter class stops the run.
  The film is the Patch #3 `LOCATION` and its capture's `.ALL`, with the parity loop's `--width 320 --height 200 --viewport-rows 185`; `--film` and `--all` name others.
* **Rounds and order.**
  `--rounds` (alias `--pairs`) runs every variant once per round.
  `--order alternate` runs them forward in even rounds and reversed in odd ones, `rotate` starts each round one variant later; the two agree for two variants.
* **Quiet machine.**
  It refuses to start, and stops between runs, while a `stuntreel`, `cargo` or `rustc` process runs; `--force` overrides.
* **Output.**
  `<out>/<name>.csv` has one row per run: the cell, round, position in the round, variant, loop and wall ms (the loop from `--report-timing`, the wall from the runner's stopwatch), the `frames`, `layers`, `palettes` and `shapes` hashes and the adapter's name and class.
  `<out>/<name>-summary.md` has, per cell, each variant's loop median, minimum, range, change against the baseline's median, "faster in N of M" rounds (a strictly smaller loop in the same round), the wall median, and whether its stores match the baseline's.
  It never overwrites either file; `--summarize <csv>` prints a committed CSV's summary again.

Commit the CSV in the work folder and link it from the journal entry that quotes its figures ([`work/README.md`](../../work/README.md#journal-entries)).
The runner's own A/A (one binary on both sides) missed the owner's bar: a median loop change of `-9.4%` against `±1%` on one run (`[Bounded Observation]`), so time a change near that size with more rounds and read the CSV's spread, not the median alone.
_Source: [the same binary on both sides of `mise run ab`](../../work/2026-11/1004_ab-timing-runner/journal.md#2026-11-23-the-same-binary-on-both-sides-of-mise-run-ab-span-b-on-lavapipe)._
