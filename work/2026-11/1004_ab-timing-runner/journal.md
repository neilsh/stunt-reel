## 2026-11-23: the same binary on both sides of `mise run ab`, Span B on lavapipe

`[Bounded Observation]`

- **Question**: Does `mise run ab` time one binary against itself within the owner's A/A bar, on Span B (`LOCATION 3680..=3979`) on lavapipe, in 4 pairs with the order alternated: a median loop change within ±1%, and neither side faster in all 4 pairs?
  The owner set the bar and asked for one run ([issue comment](https://github.com/neilsh/stunt-reel/issues/1004#issuecomment-7108307431)).
- **Method**:
  - `main` at `71b6e10d` (`--report-timing` landed), one release `stuntreel.exe` built from it with `cargo build --release -p stunt-cli`, named as both variants `a` and `b`; the runner is [`ab.py`](../../../python/scripts/ab.py) and [`ab_timing.py`](../../../python/stunt_reel/ab_timing.py) as this item's commit has them.
  - Command: `mise run ab -- --out work/2026-11/1004_ab-timing-runner --name aa-span-b --variant a --variant b --span 3680..=3979 --adapter lavapipe --rounds 4 --order alternate`, so `a` first in rounds 0 and 2 and `b` first in rounds 1 and 3.
    The runner passes `--headless <data>/builds/patch3/VAULT/LOCATION.FLM --all <data>/captures/vault-location/archives/LOCATION.ALL --tick-range 3680..=3979 --sidata <data>/corpus/siarchive/Developer/FreeFlight/SIDATA --width 320 --height 200 --viewport-rows 185 --software-only --report-timing`, with `VK_DRIVER_FILES` naming mesa-dist-win 25.2.8's `lvp_icd.x86_64.json`.
  - Quiet machine: `tasklist | grep -iE 'stuntreel|stunt-cli|cargo|rustc'` printed nothing just before the run, the build had finished before it, and the runner checks the process list before every run and refuses while one of the three runs.
  - Run once, as the owner ruled; it is not repeated.
    A one-round smoke run on `3680..=3685`, writing to `build/scratch` and not kept, came first to see the command work.
  - Raw rows: [`aa-span-b.csv`](aa-span-b.csv), the summary the runner printed: [`aa-span-b-summary.md`](aa-span-b-summary.md).
- **Result**:
  - Loop ms in round order (`--report-timing`'s `loop`), the median, the minimum and the range:

    | Side | Rounds 0 to 3 | Median | Minimum | Range |
    |---|---|---|---|---|
    | `a` | 4867.3, 4378.7, 3680.8, 4259.3 | 4319.0 | 3680.8 | 3680.8..4867.3 |
    | `b` | 3975.7, 3800.0, 3853.2, 4518.0 | 3914.5 | 3800.0 | 3800.0..4518.0 |

  - `b` against `a`: median `-9.4%` (`4319.0` to `3914.5 ms`), minimum `+3.2%`; `b` was faster in `2` of `4` pairs (rounds 0 and 1, by `18.3%` and `13.2%`; slower in rounds 2 and 3, by `4.7%` and `6.1%`).
    Whole-process wall-clock medians `7108.1` and `6515.6 ms` (`-8.3%`).
  - The eight runs of one binary spread `32.2%` (`3680.8` to `4867.3 ms`); the side that ran first in its round was slower in `2` of `4` rounds.
    `#920`'s Span B base runs on lavapipe were `2466` to `2864 ms` ([`920`'s journal](../920_unbake-world-props/journal.md#2026-11-22-loop-time-with-the-worlds-base-and-decal-draws-skipped)), so these ran slower; this entry did not isolate why.
  - Every run's `render.json` names `llvmpipe (LLVM 21.1.7, 256 bits)`, class `cpu`, and all four stores hashed the same in all eight runs.
- **Verdict**: control, missing the bar on its first condition: a median change of `-9.4%` against ±1%.
  The second condition held (neither side faster in all 4 pairs: `2` of `4`).
  Per the owner's ruling the tool ships without a re-run and `#1004` goes to `status:ready-for-human`; `#1001` does not time with the tool until the owner has seen these figures.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3, the A/A bullet; the tool's use is [`time-a-headless-render.md`](../../../docs/howto/time-a-headless-render.md) § 3.
