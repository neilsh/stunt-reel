# Time a headless render

`--report-timing` makes a headless `stuntreel` render print, to stderr, how long its start-up phases and its frame loop took.
It sits beside `--report-memory` ([Measure a headless render's memory](measure-a-renders-memory.md)) and, like it, writes no file; it reads the clock where `--report-memory` reads resident memory.
On the synthetic `synthetic_timeline.flm`, the render store was byte-identical with the flag on and off (a `diff -r` of two `--out-dir` renders on a GPU adapter, 2026-11-23, and `report_timing_prints_each_phase_and_leaves_the_store_alone` in [`timing_test.rs`](../../crates/stunt-cli/tests/it/timing_test.rs), which runs on the software adapter and skips when no software fallback adapter offers the clip distances the renderer requires (WARP lacks them; [ADR 0054](../adr/0054-depth-is-reversed-and-infinite.md)), even with `STUNT_REQUIRE_GPU=1`).
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

## 3. Time variants against each other

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
* **Warm-up.**
  `--warmup` rounds (default 1) run every variant once before a cell's first round, untimed and not kept; the runner prints their loop times.
* **Quiet machine.**
  It refuses to start, and stops before a timed run, while a `stuntreel`, `cargo` or `rustc` process runs.
  Before each timed run it measures the whole machine over 2 seconds, repeatedly for up to 10 minutes, until it is at most `--max-load` busy (a share of all logical CPUs, default `0.10`), and stops if it never is.
  During each timed run it samples every 0.25 s the CPU time of the machine and of the render, and records the rest, the share other processes used, as the row's `other_load`; a run over `--max-load` is kept in the CSV and the timing stops after it.
  Warm-up runs pass none of these checks.
  Other processes' load slows a lavapipe loop: on Span B, 8 spinning processes on the 16-thread laptop raised the median `19.3%`, and one run at `10.3%` other load ran `16.3%` slower than the slowest of the four quiet runs before it (`[Bounded Observation]`, `#1018`, [section 3 of the render-time note](../../research/parity/lavapipe-render-time.md#3-where-loop-time-goes)).
  `--force` skips all three checks.
* **Output.**
  `<out>/<name>.csv` has one row per run: the cell, round, position in the round, variant, loop and wall ms (the loop from `--report-timing`, the wall from the runner's stopwatch), the `frames`, `layers`, `palettes` and `shapes` hashes, the adapter's name and class, and `other_load`.
  `<out>/<name>-summary.md` has, per cell, each variant's loop median, minimum, range, change against the baseline's median, "faster in N of M" rounds (a strictly smaller loop in the same round), the wall median, the largest `other_load` of its runs, and whether its stores match the baseline's.
  It never overwrites either file; `--summarize <csv>` prints a committed CSV's summary again.

Commit the CSV in the work folder and link it from the journal entry that quotes its figures ([`work/README.md`](../../work/README.md#journal-entries)).
The runner's own A/A (one binary on both sides) missed the owner's bar before the load checks: a median loop change of `-9.4%` against `±1%` on one run (`[Bounded Observation]`), and the eight runs' loops spread `32.2%`, so read the CSV's spread beside the median.
_Source: [the same binary on both sides of `mise run ab`](../../work/2026-11/1004_ab-timing-runner/journal.md#2026-11-23-the-same-binary-on-both-sides-of-mise-run-ab-span-b-on-lavapipe)._
The first two A/A runs with the load checks stopped on the load check, after 5 and after 2 of 8 runs, at `10.3%` and `10.2%` other load, so neither has a verdict.
The third, at `--max-load 0.15`, completed all 8 runs at `8.9%..11.2%` other load: the medians were `2380.2 ms` (`a`) and `2354.7 ms` (`b`), a change of `-1.07%` against the `±1%` bar, with each side faster in 2 of 4 pairs and the eight loops spread `6.2%` (`2302.9..2445.3 ms`) (`[Bounded Observation]`, one machine, one binary, Span B on lavapipe).
It missed the median bar by `0.07` points, so it is not a pass; the owner accepted that one result as an exception, and the `±1%` bar and the pass rule are unchanged.
No later gate inherits the exception.
In that one completed A/A the 4-pair median moved `1.07%` and the eight loops spread `6.2%`, with other load at `0.089..0.112` (3 of 8 runs over the default `0.10` bar); a quiet probe's seven runs spread `9.6%`, so read a result's spread beside its median, and take these as one run's figures, not a bound.
A gate near that one run's spread, such as `#999`'s 2% loop gate, must size its pairs before it times anything ([#1089](https://github.com/neilsh/stunt-reel/issues/1089)); `#1001`'s gate, a median at least `5%` lower and faster in all 4 pairs, is above the `1.07%` median change of that one A/A, which sizes nothing for the single-run spreads above.
_Source: [what spreads one binary's Span B lavapipe runs](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs), [the first A/A re-run](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-25-the-owner-approved-aa-re-run-stopped-by-the-load-check), [the second, at a 15% load bar](../../work/2026-11/1018_lavapipe-ab-variance/journal.md#2026-11-25-the-second-owner-approved-aa-re-run-at-a-15-load-bar-completed-missed-the-median-bar), CSV [`aa-span-b-rerun2.csv`](../../work/2026-11/1018_lavapipe-ab-variance/aa-span-b-rerun2.csv)._
