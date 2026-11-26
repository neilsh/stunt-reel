## 2026-11-24: what spreads one binary's Span B lavapipe runs

`[Bounded Observation]`

- **Question**: Which of `#1018`'s hypotheses (warm-up, background load, CPU clock or thermals, run order) spreads one binary's Span B (`LOCATION 3680..=3979`) lavapipe loop times, which `#1004`'s A/A spread `32.2%` (`3680.8` to `4867.3 ms`) against `#920`'s `2466` to `2864 ms`?
- **Method**:
  - One release `stuntreel.exe` built from `main` at `d4f00c76` (`cargo build --release --locked -p stunt-cli`), Windows `mesa-dist-win 25.2.8` (`llvmpipe (LLVM 21.1.7, 256 bits)`), on the owner's laptop (AMD Ryzen 7 7745HX, 8 cores, 16 logical CPUs, on mains power, the "Legion Balance Mode" power plan), with the T3 and Claude sessions of this run open and idle.
  - [`load_probe.py`](load_probe.py) runs the render `mise run ab` runs (the same `render_argv` and environment) back to back, `--runs` times, and records per run the loop ms (`--report-timing`), the wall ms, the busy share of all 16 logical CPUs (`busy_all`), the render's own share (`busy_render`), the rest (`busy_other`, other processes, the probe's own sampling and `typeperf` included), sampled every 0.25 s with `psutil`, and the mean `\Processor Information(_Total)\% Processor Performance` (`perf_pct`, the effective clock against the 3.6 GHz base) from `typeperf` at 1 s.
    `--burn N` starts `N` spinning Python processes (`while True: pass`, normal priority) before run 0 and ends them after the last; `--priority high` raises the render to `HIGH_PRIORITY_CLASS`; `--idle-before S` waits `S` seconds before run 0.
  - Six probes, in this order, each `mise exec -- uv run python work/2026-11/1018_lavapipe-ab-variance/load_probe.py --out <csv>` with: `--runs 8` ([`probe-baseline.csv`](probe-baseline.csv)), `--runs 3 --idle-before 120` ([`probe-after-idle.csv`](probe-after-idle.csv)), `--runs 4 --burn 8` ([`probe-burn8.csv`](probe-burn8.csv)), `--runs 3 --burn 16` ([`probe-burn16.csv`](probe-burn16.csv)), `--runs 3 --burn 16 --priority high` ([`probe-burn16-high.csv`](probe-burn16-high.csv)) and `--runs 3 --priority high` ([`probe-high.csv`](probe-high.csv)).
    No `stuntreel`, `cargo` or `rustc` process ran beside them (`tasklist` before the first).
- **Result**:

  | Probe | Loop ms by run | Median | Spread | `busy_other` |
  |---|---|---|---|---|
  | quiet | 2659.6, 2482.7, 2563.4, 2338.1, 2440.7, 2384.1, 2378.3, 2395.4 | 2418.05 | 13.8% | 0.045..0.127 |
  | after 120 s idle | 2333.1, 2571.1, 2365.3 | 2365.3 | 10.2% | 0.039..0.059 |
  | 8 spinners | 2910.2, 2895.1, 2875.9, 2807.7 | 2885.5 | 3.7% | 0.535..0.569 |
  | 16 spinners | 4103.2, 4237.3, 4318.1 | 4237.3 | 5.2% | 0.914..0.941 |
  | 16 spinners, high priority | 3440.6, 3478.9, 27598.8 | 3478.9 | 702.2% | 0.887..0.980 |
  | high priority | 2493.9, 2342.4, 2424.6 | 2424.6 | 6.5% | 0.044..0.087 |

  Spread is (max - min) / min.
  - **Background load** slows the loop: 8 spinners (`busy_other` about `0.55`) raised the median `19.3%` over the quiet probe's (`2885.5` against `2418.05 ms`), and 16 (`0.91..0.94`) `75.2%` (`4237.3 ms`).
    The 16-spinner runs (`4103.2..4318.1 ms`) fall inside `#1004`'s A/A range (`3680.8..4867.3 ms`), whose load was not recorded, so a heavily loaded machine is consistent with that run's slow loops; it is not shown to be their cause.
    A steady load moved every run alike (spreads `3.7%` and `5.2%`); a load that comes and goes moves some runs and not others.
  - **CPU clock**: `perf_pct` stayed between `119.2` and `128.5` in every run, under load as well, and the quiet probe's slowest run (`2659.6 ms`) had its highest clock (`125.5`), so the clock does not explain the spread in these runs.
  - **Warm-up**: the first run was the slowest in the quiet probe (`2659.6 ms`, `11.0%` above the median of runs 1 to 7, `2395.4 ms`) and in the high-priority probe (`2493.9 ms`), and `#1004`'s first run was its slowest; after 120 s idle the first run was the fastest (`2333.1 ms`).
    Those slow first runs also had higher `busy_other` (`0.095` and `0.087`, against `0.039` after idle), so a first-run cost and the load of starting the probe are not separated.
  - **Raising the render's priority** under 16 spinners cut two runs to `3440.6` and `3478.9 ms` and stretched the third to `27598.8 ms`, so a high priority is not a stable fix.
  - **Residual spread on a quiet machine**: runs 1 to 7 of the quiet probe spread `9.6%` (`2338.1..2563.4 ms`) at `busy_other` `0.045..0.127`, with no ordering by `busy_other` or `perf_pct` (`2563.4 ms` at `0.053` and `120.4`, `2338.1 ms` at `0.045` and `120.5`).
- **Verdict**: background CPU load from processes the runner did not check is the cause found; warm-up stays possible (not separated from start-up load), CPU clock is ruled out on these runs, raising priority is ruled out as a fix, and run order was already ruled out by `#1004`'s A/A (the side that ran first was slower in `2` of `4` rounds).
  The runner now records other processes' load per run, waits for a quiet machine before each timed run, stops after a loaded run, and runs one untimed warm-up round: [`ab_timing.py`](../../../python/stunt_reel/ab_timing.py), [`ab.py`](../../../python/scripts/ab.py).
  What spreads quiet runs by `9.6%` is not found.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3; the runner's checks in [`time-a-headless-render.md`](../../../docs/howto/time-a-headless-render.md) § 3.

## 2026-11-24: the A/A check after the fix, stopped by the load check

`[Bounded Observation]`

- **Question**: With the runner's load checks and warm-up round, does one binary on both sides of Span B on lavapipe, 4 pairs with the order alternated, meet `#1004`'s bar: a median loop change within ±1%, and neither side faster in all 4 pairs?
- **Method**: the binary of the entry above as both `a` and `b`; `mise run ab -- --out work/2026-11/1018_lavapipe-ab-variance --name aa-span-b --variant a --variant b --span 3680..=3979 --adapter lavapipe --rounds 4 --order alternate`, with the defaults `--warmup 1` and `--max-load 0.10`, run once at 18:09 local time (`tasklist` showed no `stuntreel`, `cargo` or `rustc` first).
  Raw rows: [`aa-span-b.csv`](aa-span-b.csv); the console output, warm-up runs included: [`aa-span-b-log.txt`](aa-span-b-log.txt).
- **Result**:
  - Warm-up (not kept): `a` `2521 ms`, `b` `2360 ms`.
  - Kept rows, loop ms and other processes' load: round 0 `a` `2348.6` (`0.033`), `b` `2352.5` (`0.044`); round 1 `b` `2380.4` (`0.031`), `a` `2421.2` (`0.045`); round 2 `a` `2815.1` (`0.103`).
  - Other processes used `10.3%` of the CPUs during round 2's `a`, over the `10%` bar, so the runner stopped there, with exit 2 and no summary; that run's loop was `16.3%` above the slowest of the four before it (`2815.1` against `2421.2 ms`).
  - The four runs at `0.031..0.045` spread `3.1%` (`2348.6..2421.2 ms`).
- **Verdict**: no verdict: the check stopped before round 2's `b`, so neither condition of the bar can be judged, and as the issue rules, it was not re-run; whether to run it again is the owner's call.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3.

## 2026-11-25: the owner-approved A/A re-run, stopped by the load check

`[Bounded Observation]`

- **Question**: The same as the entry above: with the runner's load checks and warm-up round, does one binary on both sides of Span B on lavapipe, 4 pairs with the order alternated, meet `#1004`'s bar?
- **Method**: the release binary built from `origin/main` at `692beeff` as both `a` and `b`; `mise run ab -- --out work/2026-11/1018_lavapipe-ab-variance --name aa-span-b-rerun --variant a --variant b --span 3680..=3979 --adapter lavapipe --rounds 4 --order alternate`, with the defaults `--warmup 1` and `--max-load 0.10`, run once (`tasklist` showed no `stuntreel`, `cargo` or `rustc` first; the release build had just finished).
  Raw rows: [`aa-span-b-rerun.csv`](aa-span-b-rerun.csv); the console output, warm-up runs included: [`aa-span-b-rerun-log.txt`](aa-span-b-rerun-log.txt).
- **Result**:
  - Warm-up (not kept): `a` `2528 ms`, `b` `2445 ms`.
  - Kept rows, loop ms and other processes' load: round 0 `a` `2418.8` (`0.092`), `b` `2377.3` (`0.102`).
  - Other processes used `10.2%` of the CPUs during round 0's `b`, over the `10%` bar, so the runner stopped there, with exit 2 and no summary.
- **Verdict**: no verdict: the check stopped after 2 of 8 runs, so neither condition of the bar can be judged; as the issue rules, a run stopped by the load check is not re-run, and whether to run it again is the owner's call.
  Both kept runs sat at `0.092..0.102` other load, where the earlier run's first four sat at `0.031..0.045` (the entry above), so the machine was busier than then; the loads in this run were not traced to a process.
- **Lives in**: nowhere else: no figure here is a finding about the render.

## 2026-11-25: the second owner-approved A/A re-run, at a 15% load bar: completed, missed the median bar

`[Bounded Observation]`

- **Question**: The same as the entries above: with the runner's load checks and warm-up round, does one binary on both sides of Span B on lavapipe, 4 pairs with the order alternated, meet `#1004`'s bar: a median loop change within ±1%, and neither side faster in all 4 pairs?
- **Method**: the release binary built from `origin/main` at `c7dac0b6` (`cargo build --release --locked -p stunt-cli`) as both `a` and `b`; `mise run ab -- --out work/2026-11/1018_lavapipe-ab-variance --name aa-span-b-rerun2 --variant a --variant b --span 3680..=3979 --adapter lavapipe --rounds 4 --order alternate --max-load 0.15`, run once with the default `--warmup 1` (`tasklist` showed no `stuntreel`, `cargo` or `rustc` first).
  The owner approved the one extra run with a higher load bar after two runs stopped at `10.3%` and `10.2%` other load; the bar is `--max-load 0.15` (the coordinator's choice), the only change from the run before.
  Raw rows: [`aa-span-b-rerun2.csv`](aa-span-b-rerun2.csv); the console output, warm-up runs included: [`aa-span-b-rerun2-log.txt`](aa-span-b-rerun2-log.txt); the runner's summary: [`aa-span-b-rerun2-summary.md`](aa-span-b-rerun2-summary.md).
- **Result**: all 8 runs completed, stores identical on both sides.
  - Warm-up (not kept): `a` `2623 ms`, `b` `2319 ms`.
  - Kept rows, loop ms (other processes' load): round 0 `a` `2302.9` (`0.093`), `b` `2356.5` (`0.101`); round 1 `b` `2445.3` (`0.110`), `a` `2354.6` (`0.089`); round 2 `a` `2431.1` (`0.098`), `b` `2311.6` (`0.094`); round 3 `b` `2352.9` (`0.100`), `a` `2405.9` (`0.112`).
  - Other load spans `0.089..0.112`; `3` of the `8` runs (`0.101`, `0.110`, `0.112`) are over the `0.10` bar of the two earlier runs, which would have stopped this one.
  - Medians: `a` `2380.2 ms`, `b` `2354.7 ms`, so `b` is `-1.07%` against `a` (the runner's summary rounds it to `-1.1%`), outside ±1%.
  - Faster: `a` in rounds 0 and 1, `b` in rounds 2 and 3, so `2 of 4` each; neither side is faster in all 4 pairs.
  - The eight loops span `2302.9..2445.3 ms` (`6.2%`).
- **Verdict**: the median bar is missed (`-1.07%` against ±1%), the all-4-pairs condition is met, so the A/A check is **not passed**; as the issue rules, it is not re-run, and the next step is the owner's.
  What this means for the dependents: `#1004` stays open and `#1001` stays blocked, as the issue's acceptance item closes `#1004` and frees `#1001` only on a pass.
  The miss is `0.07` percentage points over the bar, at a spread of single runs (`6.2%`) several times the `±1%` bar, with `b` faster in 2 of 4 pairs; this run does not show which of load at `0.09..0.11` or the runner's method accounts for it.
- **Lives in**: nowhere else: no figure here is a finding about the render.
