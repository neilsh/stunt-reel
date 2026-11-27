# Count a headless render's instructions

`mise run icount` counts the instructions of one tick span of a headless lavapipe render on two or more builds, so a perf ticket can gate a CPU-side change on a count without a quiet machine.
The method, its repeat ranges and its verdict are in [`lavapipe-instruction-counts.md`](../../research/parity/lavapipe-instruction-counts.md); this page is how to run it.
It needs Linux with `valgrind` and `setarch`, and the lavapipe ICD that [Render on lavapipe beside a GPU](render-on-lavapipe.md) names.

## 1. Run it

Build every binary first: the runner runs them as they are.
A variant is `NAME [binary=PATH] [VAR=VALUE ...]` as in [`mise run ab`](time-a-headless-render.md#3-time-variants-against-each-other), and the first is the baseline.

```bash
mise run icount -- --out work/2026-11/<issue>_<slug> --name span-b     --variant "base binary=build/old" --variant "new binary=build/new"     --span 3680..=3709 --repeats 3
```

* **Spans.**
  Each `--span` (default `3680..=3709`, the first 30 ticks of Span B) is counted on every variant, `--repeats` times each (default 3), interleaved.
  The film and archive default to `mise run ab`'s; `--film`, `--all` and `--icd` name others.
* **Setup.**
  Each render runs under `setarch "$(uname -m)" -R valgrind --tool=cachegrind --cache-sim=no --smc-check=all-non-file` with `MESA_SHADER_CACHE_DISABLE=true` and `LP_NUM_THREADS=1`, with `mise run ab`'s render flags and `--software-only`.
  A run takes tens of times its native time ([section 4 of the note](../../research/parity/lavapipe-instruction-counts.md#4-cost)).
* **Output.**
  `<out>/<name>.csv` has one row per run: the span, variant, repeat, the whole-run count, the count outside glibc's `malloc.c` and `memmove`, and the four store hashes.
  `<out>/<name>-summary.md` has, per span and variant, both counts' median, change against the baseline's median and multiple of the baseline's repeat range, whether the stores match the baseline's, and the `--top` functions whose count differs most (the first repeat of each side).
  It never overwrites either file.
* **Exit code.**
  1 when a run fails or a store differs from the baseline's (the summary is still written), 2 on a refusal.

## 2. Reading it

Read the change outside the allocator against the range of the same span's baseline repeats: one span's range does not bound another's, and a difference of two spans' counts adds both spans' noise.
A zero range prints "no range"; add repeats or a second span before reading a multiple into it.

## 3. When a count may stand in for `mise run ab`

A count may gate a CPU-side change in the instructions of our Rust code, such as a loop, a walk or an allocation removed.
Wall time is still needed for a change in memory traffic, cache use or parallelism, for anything on the GPU, and for the final confirmation of a perf ticket ([section 5 of the note](../../research/parity/lavapipe-instruction-counts.md#5-verdict)).
