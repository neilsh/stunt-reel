# VAULT Films in the Parity Corpus (design note)

Status: design, not started. Owner: unassigned.

## 1. Why

The parity loop scores two films, `CTRY.FLM` and `INTRO.FLM`. The retail `VAULT` films show
errors those two rarely or never show ([`research/parity/batch.md`](../../../research/parity/batch.md)
§ 4): the sea band wrong on every graded `SPLANES.FLM` frame, the aircraft not drawn on 11 of 12
`LAND.FLM` frames, the balloon's sky, sun and parachute, tents drawn as cones. Adding films gives
rounds work that changes the picture where CTRY and INTRO cannot see it.

Goal: more films become **fidelity targets**, so a gain on any of them counts towards adoption, at
the smallest cost in scoring logic and sweep time.

## 2. Settled decisions

| # | Decision | Choice |
|---|---|---|
| D1 | What the new films are for | Fidelity targets, not just a regression guard: a gain on any film counts. |
| D2 | Adoption rule | The rule stays per film, with no aggregate across films. Evidence-backed: no film falls by more than 0.002 and at least one rises. Heuristic: every film gains more than 0.002, or one gains more than 0.004 while every other moves less than 0.002 either way. |
| D3 | Which films, in what order | Two at a time. Phase 1 is `vault-splanes` and `vault-land`. Phase 2 (`vault-balloon`, `vault-traintnl`) begins once phase 1 stops yielding gains; it needs only new reference rows, no code. |
| D4 | Films left out | `vault-tod` waits for a fade floor that works on night films (§ 7). `vault-bomb` and `vault-location` mostly repeat the aircraft errors CTRY already shows, and they are the two longest films. |
| D5 | Engine build of the new references | `unpatched` for both `makeone` and `playone`, the same as CTRY and INTRO, so every reference comes from one engine build. A film that stalls on the unpatched build takes `patch3`, with the cause written in `reason`. |
| D6 | Parallel scoring | `--jobs N` on `mise run parity` and `mise run sweep` runs (variant, film) render-and-score pairs at once. The default is `min(8, os.cpu_count(), pairs)`. There is no live RAM or VRAM probe; the cost per job (§ 3) is documented instead. |
| D7 | Output under parallelism | Results print in the same fixed (variant, film) order as a sequential run, so the table, the winner line and the `[parity]` lines are unchanged. |

## 3. Evidence for D6

Throwaway probe, 2026-11-06, release build of `48f5d49`. The machine has 16 logical and 8 physical
cores, 31 GiB of RAM and an RTX 4070 Laptop GPU with 8 GiB.

* **Renders run on the GPU.** Headless mode asks wgpu for the `HighPerformance` adapter
  ([`renderer.rs`](../../../crates/stunt-render/src/renderer.rs) `select_adapter`). Each render
  runs about 57 threads but keeps only 0.4 to 0.65 of a core busy.
* **The cost per render is flat.** About 300 MiB of RAM and about 200 MiB of VRAM, the same for
  `BOMB.FLM` (339 ticks drawn), `LOCATION.FLM` (751 ticks), CTRY and INTRO. A score takes about
  35 MiB and under 1.2 CPU-seconds.
* **Most of a render is start-up.** Drawing one tick takes 2.2 to 3.5 s wall, 0.8 to 0.9
  CPU-seconds and 256 to 283 MiB. The whole CTRY render takes 3.7 s, 2.1 CPU-seconds and 268 MiB;
  the whole INTRO render 6.7 s, 4.7 CPU-seconds and 270 MiB. So about 60% of a CTRY render and
  35% of an INTRO render, and nearly all of the memory, is per process, not per frame. Where the
  start-up time goes (wgpu instance and device creation, asset loading) is not measured; little
  of it is CPU.
* **Render-and-score throughput**, CTRY and INTRO alternating:

  | Jobs | Pairs/s | Peak RAM | Peak VRAM | GPU load (mean / max) |
  |---|---|---|---|---|
  | 1 | 0.25 | 0.3 GiB | — | — |
  | 8 | 0.80 | 2.1 GiB | 1.8 GiB | 37% / 76% |
  | 16 | 1.0–1.1 | 4.1 GiB | 3.2 GiB | 64% / 92% |
  | 32 | 0.83–1.30 | 8.2 GiB | 6.4 GiB | 70% / 96% |

* **Reading.** 8 jobs gives about 3x the throughput of one job. 16 jobs adds 25 to 35% for twice
  the memory. At 32 jobs the GPU is saturated: three runs measured 0.83 to 1.30 pairs/s, and 6.4 of
  the 8 GiB of VRAM was in use. With 8 jobs, a 6-variant sweep takes about 30 s on four films and
  about 60 s on eight.

## 4. Components

### 4.1 Reference rows (phase 1: `vault-splanes`, `vault-land`)

Data only. `--films` already defaults to every row `references.toml` pins
([`cli.py`](../../../python/scripts/cli.py) `parity_options`), so once a row lands, `parity` and
`sweep` score that film without any code change.

Per film:

1. Capture on the build D5 names, using `mise run capture-ref`.
2. Promote the capture through the skill's "Comparing a candidate reference" procedure: write the
   row with `film`, `sha256`, `makeone`, `playone` and `reason`. Leave out `noise_sigma` (§ 7).
3. Score it at HEAD and add a `log.md` row recording the film's baseline.
4. Run the error readout (`errors-make` / `errors-score`) once, so the film's starting categories
   are on record next to `batch.md` § 4.

### 4.2 `run_matrix` in `parity_pipeline`

One function owns rendering in parallel; `run_films` becomes its one-variant case.

```
run_matrix(films, root, variants: Sequence[tuple[Path, dict[str, str] | None]], *,
           jobs=1, retime=None, render=True, run=run_command)
    -> list[list[FilmScore | FilmFailure]]   # [variant][film], in input order
```

* Each film's reference is opened once, through `reference_job` in an `ExitStack`, on the calling
  thread. All variants share that verified snapshot (ADR 0031), so a sweep checks each film's hash
  once rather than once per variant.
* Every (variant, film) pair is submitted to a `ThreadPoolExecutor(max_workers=jobs)`. Threads are
  enough because the work runs in `stuntreel` child processes. `jobs <= 1` runs on the calling
  thread, exactly as today.
* A pair that fails becomes a `FilmFailure`, and the other pairs still run.
* Ctrl+C follows `batch_parity`'s pattern: `shutdown(cancel_futures=True)` drops pairs not yet
  started, and running children end through the runner's own process-tree kill.

### 4.3 The scripts

* **`parity_run.py`** gains `--jobs`. Its film loop moves onto `run_matrix` with a single
  variant. `--reuse` and `--no-render` keep their meaning (`render=False`).
* **`parity_sweep.py`** gains `--jobs`. It builds the variant list (workdir and env per variant),
  calls `run_matrix` once, and then runs today's per-variant post-processing over the results:
  notes, the `iou` probe, `--keep-best`. Because pairs from different variants finish
  interleaved, a variant's progress line prints once all its films are done, and render
  directories are deleted after ranking rather than per variant.
* **`--jobs` is a shared flag in [`cli.py`](../../../python/scripts/cli.py)**, next to `--films`,
  so the two scripts parse it once. The help text gives the cost per job from § 3.

### 4.4 Docs and skill

* **[`improving-render-parity`](../../../.agents/skills/improving-render-parity/SKILL.md):**
  * The adoption rule reads "every film" (D2).
  * "Score both films" becomes "Score every film".
  * The baseline step expects one line per film.
  * The cost rules mention `--jobs`.
* **[`research/parity/probes.md`](../../../research/parity/probes.md) § 4 and the `mise.toml`
  descriptions of `parity` and `sweep`** stop saying "CTRY and INTRO" and "both films".
* **[`research/parity/method.md`](../../../research/parity/method.md):** add the § 3 facts that
  concern the method: renders use the high-performance GPU adapter, and cost about 300 MiB of RAM
  and 200 MiB of VRAM each, whatever the film's length.

## 5. Testing

Offline only. A fake `Run` adapter stands in for `stuntreel`, as `tests/` already does for
`run_films`.

* **Order:** with `jobs=4` and a fake that sleeps a random time per call, results come back in
  [variant][film] input order.
* **Equivalence:** `jobs=1` and `jobs=4` give the same results for the same fake.
* **Isolation:** one failing pair yields a `FilmFailure`, and every other pair still runs.
* **Environment:** each render call receives its own variant's `env`, never another variant's.
* **One snapshot per film:** `reference_job` is entered once per film, whatever the number of
  variants.
* **Interrupt:** a `KeyboardInterrupt` raised while pairs are pending cancels them, and the
  interrupt propagates.
* **CLI:** `--jobs` parses on both scripts and defaults to `min(8, cpu_count, pairs)`; `--jobs 0`
  is a usage error.

Live check (not in `tests/`): run `mise run parity -- --jobs 1` and `mise run parity -- --jobs 8`
on the same binary. Both must print identical score lines, since identical builds render
identically ([`method.md`](../../../research/parity/method.md) § 3).

## 6. Order of work

1. `run_matrix`, its tests, and `--jobs` on both scripts. One commit. It changes no score, so it
   needs no log row.
2. Docs and skill wording (§ 4.4), in the same PR as step 1.
3. Phase-1 reference rows (§ 4.1), one commit per film, each with its `log.md` row. These need
   DOSBox, and they are the only steps that do.

## 7. Out of scope (later specs or later steps)

* **A fade floor for night films**, which `vault-tod` needs. The fade floor drops most frames of a
  night film ([`method.md`](../../../research/parity/method.md) § 2.1).
* **Drawing only the captured ticks.** Parity renders draw every tick in the capture's range;
  drawing only the scored ones (`--at-ticks`) would make each render cheaper. Retime needs the
  neighbouring ticks, so it would have to be optional.
* **`noise_sigma` for each new film.** Optional in `references.toml` (INTRO has none), and the
  adoption floor of 0.002 is a build-level bound, not this sigma.
* **Cutting render start-up** (§ 3). This is the first probe: time instance creation, adapter and
  device acquisition, pipeline creation and asset loading in one headless render. If one step
  dominates (for example `Backends::all()` initialising every backend), fixing it speeds up every
  render, sequential ones included, and needs no change to the pipeline.
* **One process rendering several jobs.** It would share one GPU device and the loaded assets, so
  it would save most of the roughly 300 MiB of RAM and 200 MiB of VRAM per job and the start-up
  time per job. Rejected for now:
  * At the default of 8 jobs, memory is not a constraint.
  * The `DBG_*` switches a sweep varies are added for one round, never committed, and read from
    the process environment with `std::env::var` (the skill's cost rule 8). Variants could share a
    process only if every such switch were threaded through a per-job config, which is the
    ceremony the throwaway switches exist to avoid.
  * One panic would lose every job in the process, and per-job timeouts would move into Rust.

  Revisit only if the start-up probe finds a cost that cannot be cut inside one render.
* **A live RAM or VRAM cap on `--jobs`.** At the default of 8, the § 3 figures leave ample room on
  this machine.
