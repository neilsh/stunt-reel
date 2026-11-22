# Journal: chunked render workers (#916)

## 2026-11-22: Worker processes on the cloud's lavapipe over the seven reference films

**Question**: does `stuntreel --workers N` write stores byte-identical to one process on every reference film, and how much wall clock does it save, for one film and for a whole `mise run parity -- --software-only` run?

**Method**: branch `claude/project-thread-2v49jm` on `dab2184` plus this change, release build; a cloud Ubuntu session with 4 vCPUs and 15 GiB, Mesa `llvmpipe (LLVM 20.1.2, 256 bits)`, no other load.
Each film was rendered once at each of `--workers 1`, `2` and `4` through `parity_pipeline.render_film` (the captured tick range, 320x200, `--viewport-rows 185`, `--software-only`), timing the wall clock and summing child CPU with `getrusage`; `--workers 1` keeps lavapipe's default `LP_NUM_THREADS`, the workers run with `LP_NUM_THREADS=1`.
Every file of each multi-worker render directory was compared byte for byte with the 1-worker one.
Then `mise run parity -- --software-only --no-build --workers N` ran once each for N = 1, 2 and 4, with the default jobs (4, 2 and 1 after the budget), and its `_current` trees were compared the same way.

**Result**: every multi-worker render directory, at 2 and 4 workers on all seven films, from the script and from `mise run parity`, matched the 1-worker one in every file (`frames.zst`, `layers.zst`, `palettes.zst`, `shapes.zst`, `render.json`, `preview/`), and the seven films' scores were the same in all three parity runs.
The largest child peak RSS was 949 MiB.

| Film (rendered ticks) | 1 worker wall, CPU | 2 workers wall, CPU | 4 workers wall, CPU | 4-worker speed-up |
|---|---|---|---|---|
| LOCATION 12..=8262 (8,251) | 140.5 s, 253.7 s | 112.3 s, 249.6 s | 76.1 s, 260.7 s | 1.85x |
| INTRO 12..=3818 (3,807) | 84.7 s, 139.4 s | 61.7 s, 133.6 s | 42.2 s, 135.1 s | 2.01x |
| BOMB 12..=3730 (3,719) | 30.3 s, 58.6 s | 31.5 s, 57.6 s | 19.9 s, 55.9 s | 1.52x |
| BALLOON 12..=1190 (1,179) | 66.4 s, 83.3 s | 36.5 s, 80.7 s | 25.9 s, 85.2 s | 2.56x |
| CTRY 14..=1333 (1,320) | 6.2 s, 15.0 s | 6.8 s, 14.7 s | 4.5 s, 15.5 s | 1.38x |
| LAND 12..=1134 (1,123) | 9.3 s, 16.5 s | 7.6 s, 16.5 s | 5.4 s, 16.8 s | 1.72x |
| TRAINTNL 12..=1233 (1,222) | 7.6 s, 15.8 s | 7.0 s, 16.0 s | 4.6 s, 15.9 s | 1.65x |

The whole parity run, rendering and scoring, took 201.3 s at `--workers 1` (4 jobs), 185.1 s at `--workers 2` (2 jobs) and 192.7 s at `--workers 4` (1 job).

**Verdict**: adopted as an opt-in flag, default 1.
One film renders 1.4x to 2.6x faster at 4 workers on 4 vCPUs, against the best single process (lavapipe's own threads already use about 1.8 cores of LOCATION's, 253.7 s CPU over 140.5 s), within 3% of the same total CPU.
Two workers were slower than one on BOMB (0.96x) and CTRY (0.91x), whose renders are short beside each worker's scene build.
On these 4 vCPUs a seven-film run gains at most 8% (185.1 s against 201.3 s), because four film jobs already fill the cores; the workers pay off where one film is rendered alone, or where cores outnumber the films still rendering.
One run per cell, so the figures are `[Bounded Observation]` on this machine only.

**Lives in**: [`research/parity/lavapipe-render-time.md` § 5](../../../research/parity/lavapipe-render-time.md#5-multi-vkdevice-in-process-versus-child-processes).
