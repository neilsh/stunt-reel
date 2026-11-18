# Measure a render's memory

`mise run render-memory` renders one reference film headless with the parity pipeline's command and prints each run's peak and steady memory, its wall time and its render stores' digests. What a LOCATION render's memory goes to is [`research/parity/evidence-limits.md`](../../research/parity/evidence-limits.md) § 3.

## 1. One build

```bash
mise run render-memory -- --film location --ticks 12..=120
```

This builds the release binary, then renders the ticks given. Without `--ticks` it renders every tick from the film's first captured tick to its last. `--no-build` reuses the binary as it is. `--software-only` renders on lavapipe or WARP beside a GPU ([render on lavapipe](render-on-lavapipe.md)).

## 2. Two builds

Build the "before" with `mise run build-at -- <rev> <out>` ([score a render change](score-a-render-change.md) § 3), then name both:

```bash
mise run render-memory -- --film location --ticks 12..=120 \
    --binary before=build/scratch/stuntreel-before --binary after=target/release/stuntreel --runs 2
```

Runs alternate (before, after, before, after), so drift on the machine falls on both. Naming a `--binary` builds no binary, so build the "after" first. The release binary is still needed: it links the film's archive into `target/linked/` when that is missing or stale.

## 3. Read the output

The command above, on a cloud session's lavapipe with `--software-only`, before and after #706:

```text
before #1: peak 1002 MiB, steady 817 MiB, 10.8 s; stores 56980ad4 9f90d1ac 42100b14
after #1: peak 748 MiB, steady 561 MiB, 8.5 s; stores 56980ad4 9f90d1ac 42100b14
before #2: peak 1004 MiB, steady 820 MiB, 8.5 s; stores 56980ad4 9f90d1ac 42100b14
after #2: peak 748 MiB, steady 557 MiB, 8.6 s; stores 56980ad4 9f90d1ac 42100b14
stores identical over all 4 runs
```

* **Peak** is the process's high-water resident set. On Linux and macOS it is `ru_maxrss` from `wait4`, the kernel's own high-water mark rather than a sample. On Windows it is the peak working set, which is the system's own high-water mark too but is read every 0.1 s, so growth after the last read is missed. Peak private bytes follow as `(private N MiB)`.
* **Steady** is the median resident set, sampled every 0.1 s, over the last four fifths of the run. The first fifth is meant to hold start-up and the world's upload.
* **Stores** are the first eight hex digits of the SHA-256 of `frames.zst`, `layers.zst` and `palettes.zst`. The last line says whether every run drew the same pixels, and names each run's digests when they differ. Compare digests only between runs of one invocation, or runs given the same `--ticks`.

Each run's store and output are in `build/scratch/render-memory/<film>/<label>_<n>/`. The script is [`render_memory.py`](../../python/scripts/render_memory.py).
