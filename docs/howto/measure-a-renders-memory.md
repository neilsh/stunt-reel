# Measure a render's memory

`mise run render-memory` renders one reference film headless with the parity pipeline's command and prints each run's peak and steady memory, its wall time and its render stores' digests. What a LOCATION render's memory goes to is [`research/parity/evidence-limits.md`](../../research/parity/evidence-limits.md) § 3.

## 1. One build

```bash
mise run render-memory -- --film location --ticks 12..=120
```

This builds the release binary and renders the ticks, or the film's captured ticks without `--ticks`. `--no-build` reuses the binary as it is. `--software-only` renders on lavapipe or WARP beside a GPU ([render on lavapipe](render-on-lavapipe.md)).

## 2. Two builds

Build the "before" with `mise run build-at -- <rev> <out>` ([score a render change](score-a-render-change.md) § 3), then name both:

```bash
mise run render-memory -- --film location --ticks 12..=120 \
    --binary before=build/scratch/stuntreel-before --binary after=target/release/stuntreel --runs 2
```

Runs alternate (before, after, before, after), so drift on the machine falls on both. Naming a `--binary` builds nothing, so build the "after" first.

## 3. Read the output

```text
before #1: peak 1002 MiB, steady 817 MiB, 10.8 s; stores 56980ad4 9f90d1ac 42100b14
after #1: peak 748 MiB, steady 561 MiB, 8.5 s; stores 56980ad4 9f90d1ac 42100b14
stores identical over all 2 runs
```

* **Peak** is the process's high-water resident set. On Linux and macOS it is `ru_maxrss` from `wait4`, which is exact. On Windows it is the peak working set, sampled every 0.1 s, with peak private bytes beside it as `(private N MiB)`.
* **Steady** is the median resident set over the last four fifths of the run, past start-up and the world's upload.
* **Stores** are the first eight hex digits of the SHA-256 of `frames.zst`, `layers.zst` and `palettes.zst`. The last line says whether every run drew the same pixels, and names each run's digests when they differ.

Each run's store and output are in `build/scratch/render-memory/<film>/<label>_<n>/`. The script is [`render_memory.py`](../../python/scripts/render_memory.py).

Give `--ticks` to both sides of a comparison. With it the render takes `--at-ticks`; without it, `--tick-range` over the captured ticks. The two can write different stores for the same frames, so their digests are not comparable.
